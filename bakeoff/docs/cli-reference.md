# Bakeoff CLI Reference

This is the one-click command reference for the Bakeoff Claude Code plugin,
Codex plugin manifest, and shared Go CLI. The root README explains when to use
each workflow; this page keeps the flags and machine-readable modes in one
place.

## Plugin Commands

| Command | Purpose |
| --- | --- |
| `/bakeoff:setup [--yes]` | Build or update the bundled Go CLI in persistent plugin data. |
| `/bakeoff:setup --from-release --version vX.Y.Z [--yes]` | Optional no-Go path: install a released CLI binary from GitHub Releases. |
| `/bakeoff:quickstart` | Check the CLI, then run `doctor --json` with provider auth probes. |
| `/bakeoff:run <path or request> [flags]` | Validate and run an existing work order, or draft one from natural language. |
| `/bakeoff:history [limit] [flags]` | List recent runs with run ids, states, and short goal summaries. |
| `/bakeoff:inspect [latest or run-id] [flags]` | Read ledgers, reports, decisions, triage, and build handoff artifacts. |
| `/bakeoff:doctor [flags]` | Run readiness diagnostics through the CLI. |
| `/bakeoff:uninstall` | Remove Bakeoff-owned plugin state and cache, then ask you to run the manual plugin uninstall. |

`/bakeoff:run` accepts either a work-order path or natural language. Natural
language drafts show a compact review preview, include full JSON inline only
when it stays readable, and wait for an explicit approval such as `yes`,
`approve`, or `run it` before the plugin writes or runs anything. Reply `show`
to print verbose JSON before approving. Straightforward build drafts use
`bakeoff draft-build` internally so canonical build JSON is generated and
validated before preview.

Generated drafts keep exactly two providers. The canonical default pair is
`claude/sonnet` plus `codex/gpt-5.5` with a `claude/opus` judge. If Codex is
not available and exactly one optional peer (`gemini` or `copilot`) is ready,
natural-language drafting may use `claude` plus that peer and call out the
fallback in the preview. Existing work-order paths are never rewritten or
substituted. Adding a third provider after a completed non-build run uses
`bakeoff escalate`; it is not a work-order schema change.

Natural-language route cues used by `/bakeoff:run` previews:

| User phrase | Route advisor |
| --- | --- |
| `build ...` with acceptance criteria, edit scope, and a gate | `Why this loop: build-verifier path` |
| `audit this report`, `second opinion on this report`, `fight the findings`, or bare `dispute this report` | `Why this loop: witness audit of current report` |
| `is finding F-007 real` | `Why this loop: focused dispute packet` |
| `second opinion on the question` or `add Gemini to this completed run` | `Why this loop: fresh third answer` |
| Formatter-only, vague one-pass, or otherwise weak-fit requests | `Why this loop: single-agent advised`; reply `draft anyway` to continue |

`Why this loop: build-verifier path` belongs to normal build previews, not
`bakeoff escalate`; build escalation is unsupported.

Recognized `/bakeoff:run` flags:

| Flag | Routed to | Meaning |
| --- | --- | --- |
| `--out <dir>` | research, build | Run ledger directory. Default: `runs`. |
| `--run-id <id>` | research, build | Explicit run id. |
| `--quiet` | research, build | Suppress heartbeat lines. |
| `--keep-worktrees` | build only | Retain build worktrees for debugging. |
| `--no-triage` | research only | Skip automatic triage for code-review runs. |
| `--no-repo-layout` | research, build | Suppress generated `<repo_layout>` prompt context. |

Mode-specific flags stop execution when they are supplied for the wrong final
type. Existing work-order paths are validated first, then `type: "build"`
routes to `bakeoff build`; `gather`, `compare`, and `analyze` route to
`bakeoff research`.

`/bakeoff:history` is a Claude plugin convenience command. It calls
`bakeoff ls --history --limit <N>` so the CLI owns run sorting, limiting, and
summary extraction. It prints the latest 10 runs by default. Recognized flags:

| Flag | Meaning |
| --- | --- |
| positional `limit` | Number of rows to show. Default: `10`. |
| `--out <dir>` | Run ledger directory. Default: `runs`. |
| `--facet <id>` | Filter by facet id. |
| `--triage-state <state>` | Filter by `no`, `dry_run`, `yes`, or `stale`. |
| `--type <type>` | Filter by `gather`, `compare`, `analyze`, `build`, or `escalation`. |

## Launcher Resolution

Bakeoff omits an explicit plugin version so Claude Code uses the plugin's git
SHA as the update key. Internal users get new plugin source when the marketplace
updates, then rerun `/bakeoff:setup` to rebuild the CLI from that source.

Both plugin surfaces use the same launcher contract:

```text
BAKEOFF_GO_BINARY
  -> ${BAKEOFF_PLUGIN_DATA}/bin/bakeoff
  -> ${CLAUDE_PLUGIN_DATA}/bin/bakeoff
  -> <plugins-root>/data/<plugin>-<marketplace>/bin/bakeoff
  -> ${CLAUDE_PLUGIN_ROOT}/dist/bakeoff
  -> go run ./cmd/bakeoff
```

The conventional data path is derived only when the plugin root matches either
`<plugins-root>/marketplaces/<marketplace>/<plugin>` or
`<plugins-root>/cache/<marketplace>/<plugin>/<version>`. Resolution is
order-only: data-dir binaries beat `dist/bakeoff`; mtimes and hashes are not
tie-breakers.

By default, `/bakeoff:setup` runs `go build` against
`${CLAUDE_PLUGIN_ROOT}/cmd/bakeoff` and installs the result at
`${CLAUDE_PLUGIN_DATA}/bin/bakeoff`. This requires Go 1.24+ and may download Go
modules through the normal Go toolchain cache on first setup.

`scripts/bakeoff-ensure-cli --check` only checks configured, setup-installed, or
packaged binaries; it does not build. `--print-path` prints only the resolved
executable path for launch helpers. Running `scripts/bakeoff-ensure-cli`
without `--check` may build `dist/bakeoff` from source when Go is available.
Successful setup deletes root `dist/bakeoff` so later plugin sessions prefer the
installed data binary instead of a stale cache artifact.

The optional release-binary setup path verifies `checksums.txt` first:

```text
/bakeoff:setup --from-release --version vX.Y.Z
```

Release downloads default to
`https://github.com/mstefanko/claude-plugins/releases/download/<tag>`.
`BAKEOFF_RELEASE_REPOSITORY` can override the owner/repo portion of that URL,
and `BAKEOFF_RELEASE_BASE_URL` can point at a mirror or `file://` test release.
Codex installs do not use `CODEX_PLUGIN_DATA` in v1; use `BAKEOFF_GO_BINARY`,
`dist/bakeoff`, or source setup there until a persistent Codex data path is
documented.

## Root Command

```text
bakeoff [-h] [--version]
```

Subcommands:

```text
init, draft-build, validate, research, build, rerun, escalate, triage, bundle, runs, ls, show, doctor
```

## `bakeoff init`

```text
bakeoff init {gather|compare|analyze|review|build} [--force]
```

Writes a starter work order in the current directory. `review` is a recipe, not
a runtime type; it writes a `gather` work order with `facet.id:
"code-review"`.

Flags:

| Flag | Meaning |
| --- | --- |
| `--force` | Overwrite an existing template file. |

## `bakeoff draft-build`

```text
bakeoff draft-build --id ID --goal TEXT --acceptance TEXT --scope TEXT --gate ID=COMMAND [flags]
```

Prints one validated `type: "build"` work order to stdout and writes nothing
to disk. Use `init build` when you want a human TODO template file; use
`draft-build` when extracted build inputs are already known and you want
approval-ready JSON.

Required repeatable flags:

| Flag | Meaning |
| --- | --- |
| `--id <slug>` | Work-order id and suggested filename stem. |
| `--goal <text>` | One-sentence implementation goal. |
| `--acceptance <text>` | Observable acceptance criterion. At least one required. |
| `--scope <text>` | Edit boundary such as a file, package, route, or narrow scope. At least one required. |
| `--gate <id>=<command>` | Gate verifier command. At least one required. |

Optional flags include `--base-ref`, repeatable `--background`, repeatable
`--protected-path`, `--comparison-goal`, `--budget-wall-seconds`,
`--budget-max-output-bytes`, `--gate-wall-seconds`, and
`--gate-max-output-bytes`. Repeat `--provider` exactly twice to choose a
non-default pair, using `backend` or `backend:model`; the generated work order
preserves the order of the two flags. Gate commands are emitted as
`["sh", "-c", "<command>"]`. Metric verifier drafting remains manual for now.

Example:

```sh
bakeoff draft-build \
  --id lscmd-finished-at-ordering \
  --goal "Order ls output by finished_at descending" \
  --acceptance "Rows are sorted by finished_at descending." \
  --scope "internal/commands/lscmd" \
  --provider claude \
  --provider gemini:pro \
  --gate "tests=go test ./internal/commands/lscmd -run TestLsOrder -count=1"
```

## `bakeoff validate`

```text
bakeoff validate WORK_ORDER
bakeoff validate context WORK_ORDER [--provider ID] [--no-repo-layout]
```

Loads JSON or JSONC, validates schema fields, prints the mode, facet, budgets,
scope policy, providers, and judge, then exits without running providers.
For build metric verifiers, validation rejects missing `metric.min_delta_percent`
and warns about omitted `metric.noise_floor_percent`, one-run noise floors,
unprotected repo-relative metric commands, and final JSON `n` requirements when
`metric.min_runs > 1`.
Validation also warns when `goal` or `background` mention path-like tokens that
do not exist under the current invocation directory.
For judge-heavy work orders (`compare`, `analyze`, `build`, and code-review
`gather`), validation may also emit an advisory-only warning when the judge
shares provider-family metadata with one or both providers. It does not probe
provider readiness; use `bakeoff doctor` to check ready non-contestant judge
backends.

`bakeoff validate context` previews the prompt context blocks providers would
receive from the current invocation directory. It prints the resolved context
root, validation warnings, the author `<context>` block, any scoped
`<repo_layout>` block, and per-provider notes. Use `--provider <id>` to preview
one provider.

## `bakeoff research`

```text
bakeoff research WORK_ORDER [flags]
```

Runs `gather`, `compare`, or `analyze` work orders. A review run is `gather`
plus `facet.id: "code-review"`.

Flags:

| Flag | Meaning |
| --- | --- |
| `--out <dir>` | Run ledger directory. Default: `runs`. |
| `--run-id <id>` | Explicit run id. |
| `--force` | Replace an existing run directory. |
| `--quiet` | Suppress provider heartbeat lines. |
| `--no-triage` | Skip automatic triage for code-review runs. |
| `--base <ref>` | Capture git review context against a base ref. Default for review context: `HEAD`. |
| `--diff` | Include a bounded unified patch in generated review context. |
| `--changed-files` | Include changed-file context against the base ref. |
| `--json` | Emit a final JSON summary. |
| `--no-repo-layout` | Suppress generated `<repo_layout>` prompt context. |

Review context is generated only when `--base`, `--diff`, or `--changed-files`
is set. The generated context includes metadata, diffstat, and changed files;
`--diff` also includes a bounded patch.

## `bakeoff build`

```text
bakeoff build WORK_ORDER [flags]
```

Runs a competitive build bakeoff in detached provider worktrees. Build mode
captures candidate patches and verifier artifacts, but it does not apply,
merge, commit, push, open a PR, or synthesize provider patches.

Flags:

| Flag | Meaning |
| --- | --- |
| `--out <dir>` | Run ledger directory. Default: `runs`. |
| `--run-id <id>` | Explicit run id. |
| `--force` | Replace an existing run directory. |
| `--quiet` | Suppress provider and verifier heartbeat lines. |
| `--json` | Emit a final JSON summary. |
| `--keep-worktrees` | Retain build worktrees for debugging. |
| `--no-repo-layout` | Suppress generated `<repo_layout>` prompt context. |

Build work orders require at least one `kind: "gate"` verifier. Metric
verifiers are optional. A provider patch is eligible only after a successful
provider run, patch capture, scope checks, and gate verification.
Metric selectors remain conservative: `metric.min_delta_percent` is required,
`metric.noise_floor_percent` should be explicit, and repeated metric runs should
emit a final aggregate JSON object with `n`.

## `bakeoff rerun`

```text
bakeoff rerun SOURCE_RUN_ID [flags]
```

Replays a previous run's `work-order.json` with a fresh run id. Build reruns run
against the current source tree, not a snapshot of the original checkout.

Flags:

| Flag | Meaning |
| --- | --- |
| `--out <dir>` | Run ledger directory. Default: `runs`. |
| `--run-id <id>` | Explicit new run id. |
| `--quiet` | Suppress provider heartbeat lines. |
| `--no-triage` | Skip automatic triage for code-review research reruns. |
| `--judge-only` | Retry only a failed research judge using durable provider artifacts from the source run. |
| `--no-repo-layout` | Suppress generated `<repo_layout>` prompt context for replayed provider runs. |

`--judge-only` is only for research runs whose providers completed and whose
judge has durable failed-attempt evidence in `decision.json` or
`judge/status*.json`. It creates a fresh run directory, copies provider
artifacts, updates `latest`, and leaves the source run unchanged.

## `bakeoff escalate`

```text
bakeoff escalate SOURCE_RUN_ID --provider BACKEND[:MODEL] --mode independent|witness|dispute [flags]
```

Runs one post-run provider escalation for an existing `gather`, `compare`, or
`analyze` source run. Code review is supported as `gather` with
`facet.id: "code-review"`. Build escalation is unsupported.

Escalation writes a new run directory with `source-run.json`,
`escalation/mode.json`, `decision.json`, `report.md`, `meta.json`, and
`manifest.json`; the source run is never mutated. `source-run.json` includes a
source triage snapshot with `source_triage.state` set to `absent` when no source
triage artifacts existed at escalation time.

Modes:

| Mode | Meaning | Calls |
| --- | --- | --- |
| `independent` | Fresh third answer. Compare/analyze then run one escalation synthesis judge; gather/review run one union judge. | 1 provider + 1 judge |
| `witness` | Audit the current report, decision, provider outputs, judge passes, and triage when present; code-review runs get an adversarial audit contract. Advisory only. | 1 provider |
| `dispute` | Build `escalation/dispute-packet.json` from contested points and ask the added provider to answer only those. Advisory only. | 1 provider |

Flags:

| Flag | Meaning |
| --- | --- |
| `--out <dir>` | Run ledger directory. Default: `runs`. |
| `--run-id <id>` | Explicit escalation run id. |
| `--dry-run` | Validate source artifacts, mode, provider, scope, and print the call envelope without creating a run. |
| `--provider <backend[:model]>` | Added provider. The provider id is the backend name. |
| `--mode <mode>` | `independent`, `witness` (audit/adversarial audit for code-review runs), or `dispute`. |
| `--scope <scope>` | Added-provider scope when it cannot be inferred. |
| `--quiet` | Suppress provider heartbeat lines. |
| `--json` | Emit a final JSON summary. |
| `--no-triage` | Skip automatic triage for code-review escalation. |
| `--no-repo-layout` | Suppress generated repo layout context for independent mode. |

Always use `--dry-run` for a preview before spending provider calls unless the
operator has already approved the exact mode.

## `bakeoff show`

```text
bakeoff show RUN_ID [flags]
```

Prints `report.md` for a run. Artifact flags are mutually exclusive.
Normal report output also prints derived source/escalation relationships when
the run's manifest links it to escalation children or a source run.

Flags:

| Flag | Meaning |
| --- | --- |
| `--out <dir>` | Run ledger directory. Default: `runs`. |
| `--judge` | Show judge output artifacts. |
| `--judge-prompt` | Show judge prompt artifacts. |
| `--triage` | Show triage output. |

`RUN_ID` can be `latest`.

## `bakeoff bundle`

```text
bakeoff bundle RUN_ID [flags]
```

Prints a derived source-run reconstruction report. Starting from a source run,
it lists the source report, source triage state, child escalation reports, child
triage states, and operator next steps for missing, stale, failed, or
zero-selected triage. Starting from an escalation run resolves back to its
source run first. The source run is not mutated unless `--write` is supplied.

Flags:

| Flag | Meaning |
| --- | --- |
| `--out <dir>` | Run ledger directory. Default: `runs`. |
| `--write` | Write derived `related-report.md` under the source run. |

## `bakeoff triage`

```text
bakeoff triage RUN_ID [flags]
```

Runs or reruns triage on a completed report. Triage verifies actionable review
findings and writes triage artifacts under `runs/<run-id>/triage/`.

Flags:

| Flag | Meaning |
| --- | --- |
| `--out <dir>` | Run ledger directory. Default: `runs`. |
| `--force` | Replace an existing triage directory. |
| `--dry-run` | Build triage inputs without invoking a provider. |
| `--quiet` | Suppress provider heartbeat lines. |
| `--json` | Emit a final JSON summary. |

## `bakeoff ls`

```text
bakeoff ls [flags]
```

Lists runs in the output directory.

Flags:

| Flag | Meaning |
| --- | --- |
| `--out <dir>` | Run ledger directory. Default: `runs`. |
| `--json` | Emit a manifest-backed JSON listing. |
| `--facet <id>` | Filter by facet id. |
| `--triage-state <state>` | Filter by `no`, `dry_run`, `yes`, or `stale`. |
| `--type <type>` | Filter by `gather`, `compare`, `analyze`, `build`, or `escalation`. |
| `--source-run <run-id>` | Filter to escalation rows linked to the given source run id. |
| `--limit <n>` | Limit rows after filtering. With `--history`, default is `10`; without it, no limit is applied unless this flag is set. |
| `--history` | Emit a compact recent-run history table with `work-order.json` summaries for displayed rows. Cannot be combined with `--json`. |

In `--json` mode, escalation rows include `source_run_id`, `source_type`,
`escalation_mode`, and `added_provider`. These keys are omitted from source
rows.

## `bakeoff runs verify`

```text
bakeoff runs verify RUN_ID [flags]
```

Verifies one run ledger, including required artifacts, manifest state,
fingerprints, and triage state.

Flags:

| Flag | Meaning |
| --- | --- |
| `--out <dir>` | Run ledger directory. Default: `runs`. |
| `--json` | Emit a parseable JSON verification report. |

`RUN_ID` can be `latest`. Path-like run ids are allowed only when they stay
inside `--out`.

## `bakeoff doctor`

```text
bakeoff doctor [flags]
```

Checks provider CLIs, local readiness, scope controls, default models, cwd
writability, default-pair fallback status, and provider auth/session state
unless auth probes are skipped. Missing Gemini or Copilot does not fail doctor;
missing Claude, missing `git`, or no runnable two-provider pair does.

Flags:

| Flag | Meaning |
| --- | --- |
| `--build` | Run live provider edit probes in temporary workspaces. |
| `--skip-auth-probe` | Skip spendful provider auth probes. |
| `--quiet` | Suppress provider heartbeat lines. |
| `--json` | Emit a parseable JSON readiness report. |

JSON output includes `canonical_default_pair`, `selected_default_pair`,
`fallback_candidates`, `fallback_requires_user_choice`,
`canonical_default_available`, `runnable_default_pair_available`, and a
`providers` map with per-backend availability, default model, auth probe, scope
capabilities, provider family, and build preflight details when requested. It
also includes `judge_family_advisory`, an advisory-only provider-family
relation for the default generated judge and selected default pair.

`judge_family_advisory` has this shape:

- `judge_backend`: default generated judge backend.
- `judge_family`: provider/catalog family for the judge backend.
- `provider_backends`: selected default provider pair.
- `relation`: one of `same_as_all`, `same_as_some`, `different_from_all`, or
  `unknown`.
- `ready_non_contestant_judges`: ready known backends whose provider family is
  not in the selected provider pair.
- `advisory_only`: always `true`; doctor does not change defaults.
- `independence_not_measured_yet`: always `true`; provider-family difference is
  metadata, not a measured independence guarantee.

Human output prints a `judge family advisory` line only when the default judge
has relation `same_as_some` or `same_as_all` and at least one ready
non-contestant judge backend exists. Otherwise the JSON field remains available
for tooling, but the human report stays quiet.

## Manifest Telemetry

Each completed run writes `manifest.json.telemetry` for local-only analysis.
Telemetry schema version `2` uses stable structural keys and meaningful nulls:
nullable keys such as `source_run_id`, `rerun_mode`,
`judge.family`, and `triage.highest_severity` remain present when their value is
unknown or inapplicable.

`route` records the resolved run type, facet id, escalation mode, and source
type. Run type follows the work order, with escalation runs reported as
`escalation`. Judge-only reruns also project `source_run_id` and
`rerun_mode: "judge_only"` at the manifest and telemetry top level, and
`bakeoff ls --json` includes those fields when present.

`providers.backends` preserves work-order order and duplicate participants.
`providers.count` is the participant count, not a deduped backend count.
`providers.families` is a sorted set of known provider families; unknown
backends are excluded from that set, while `family_diversity: "unknown"` records
that at least one backend was not in the catalog. Otherwise
`family_diversity` is `single` or `mixed`.

`judge` records the configured or resolved judge backend/family, family
relation to the provider set, whether the judge ran and completed,
`selection_basis`, winner backend/family, `order_maps`, `judge_passes`, and
whether a position swap was used. A missing judge backend has null family and
family relation; an unrecognized non-empty judge backend uses family
`unknown`.

`artifacts` records local counts such as prompt trims and output truncation
events. Build diagnostics are authoritative when present. `triage` records
state, item count, and highest actionable severity. Highest severity only rolls
up `real_issue` items; false positives, evidence gaps, and needs-repro items do
not raise the actionable severity.

## JSON Modes

These commands have `--json` output intended for scripts:

- `bakeoff research --json`
- `bakeoff build --json`
- `bakeoff triage --json`
- `bakeoff ls --json`
- `bakeoff runs verify --json`
- `bakeoff doctor --json`

JSON mode also implies quieter operation for run-style commands.

For `bakeoff build --json`, `selected_patch_status` is always present.
`selected_patch_path` is present only when `selected_patch_status` is
`selected` and is relative to the run directory, for example
`providers/claude/build/diff.patch`.

## Exit Codes

| Exit | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Runtime, provider, verifier, or build failure. |
| `2` | Usage, config, validation, or missing-input error. |
| `3` | Completed run with unresolved judge disagreement. |
| `4` | Decision incomplete: judge failed or did not converge. Research runs with successful providers can use `bakeoff rerun <run-id> --judge-only`; build judge failures also use exit `4`, but build runs have no selected patch unless `decision.json.canonical_winner` is non-null. |
| `130` | Interrupted. |

Exit code `3` is a completed Bakeoff handoff. Inspect `decision.json` and
`report.md`; do not treat it as a corrupt ledger.
