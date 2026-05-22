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
substituted.

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
| `--type <type>` | Filter by `gather`, `compare`, `analyze`, or `build`. |

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
init, draft-build, validate, research, build, rerun, triage, runs, ls, show, doctor
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
Validation also warns when `goal` or `background` mention path-like tokens that
do not exist under the current invocation directory.

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

## `bakeoff show`

```text
bakeoff show RUN_ID [flags]
```

Prints `report.md` for a run. Artifact flags are mutually exclusive.

Flags:

| Flag | Meaning |
| --- | --- |
| `--out <dir>` | Run ledger directory. Default: `runs`. |
| `--judge` | Show judge output artifacts. |
| `--judge-prompt` | Show judge prompt artifacts. |
| `--triage` | Show triage output. |

`RUN_ID` can be `latest`.

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
| `--type <type>` | Filter by `gather`, `compare`, `analyze`, or `build`. |
| `--limit <n>` | Limit rows after filtering. With `--history`, default is `10`; without it, no limit is applied unless this flag is set. |
| `--history` | Emit a compact recent-run history table with `work-order.json` summaries for displayed rows. Cannot be combined with `--json`. |

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
capabilities, and build preflight details when requested.

## JSON Modes

These commands have `--json` output intended for scripts:

- `bakeoff research --json`
- `bakeoff build --json`
- `bakeoff triage --json`
- `bakeoff ls --json`
- `bakeoff runs verify --json`
- `bakeoff doctor --json`

JSON mode also implies quieter operation for run-style commands.

## Exit Codes

| Exit | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Runtime, provider, verifier, or build failure. |
| `2` | Usage, config, validation, or missing-input error. |
| `3` | Completed run with unresolved judge disagreement. |
| `4` | Decision incomplete: judge failed or did not converge; provider artifacts are durable and `bakeoff rerun <run-id> --judge-only` is recommended when providers succeeded. |
| `130` | Interrupted. |

Exit code `3` is a completed Bakeoff handoff. Inspect `decision.json` and
`report.md`; do not treat it as a corrupt ledger.
