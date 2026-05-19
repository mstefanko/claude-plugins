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
| `/bakeoff:inspect [latest or run-id] [flags]` | Read ledgers, reports, decisions, triage, and build handoff artifacts. |
| `/bakeoff:doctor [flags]` | Run readiness diagnostics through the CLI. |
| `/bakeoff:uninstall` | Remove Bakeoff-owned plugin state and cache, then ask you to run the manual plugin uninstall. |

`/bakeoff:run` accepts either a work-order path or natural language. Natural
language drafts must show the full JSON and wait for an explicit approval such
as `yes`, `approve`, or `run it` before the plugin writes or runs anything.

Recognized `/bakeoff:run` flags:

| Flag | Routed to | Meaning |
| --- | --- | --- |
| `--out <dir>` | research, build | Run ledger directory. Default: `runs`. |
| `--run-id <id>` | research, build | Explicit run id. |
| `--quiet` | research, build | Suppress heartbeat lines. |
| `--keep-worktrees` | build only | Retain build worktrees for debugging. |
| `--no-triage` | research only | Skip automatic triage for code-review runs. |

Mode-specific flags stop execution when they are supplied for the wrong final
type. Existing work-order paths are validated first, then `type: "build"`
routes to `bakeoff build`; `gather`, `compare`, and `analyze` route to
`bakeoff research`.

## Launcher Resolution

Bakeoff omits an explicit plugin version so Claude Code uses the plugin's git
SHA as the update key. Internal users get new plugin source when the marketplace
updates, then rerun `/bakeoff:setup` to rebuild the CLI from that source.

Both plugin surfaces use the same launcher contract:

```text
BAKEOFF_GO_BINARY
  -> ${BAKEOFF_PLUGIN_DATA}/bin/bakeoff
  -> ${CLAUDE_PLUGIN_DATA}/bin/bakeoff
  -> ${CLAUDE_PLUGIN_ROOT}/dist/bakeoff
  -> go run ./cmd/bakeoff
```

By default, `/bakeoff:setup` runs `go build` against
`${CLAUDE_PLUGIN_ROOT}/cmd/bakeoff` and installs the result at
`${CLAUDE_PLUGIN_DATA}/bin/bakeoff`. This requires Go 1.24+ and may download Go
modules through the normal Go toolchain cache on first setup.

`scripts/bakeoff-ensure-cli --check` only checks configured, setup-installed, or
packaged binaries; it does not build. Running `scripts/bakeoff-ensure-cli`
without `--check` may build `dist/bakeoff` from source when Go is available.

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
init, validate, research, build, rerun, triage, runs, ls, show, doctor
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

## `bakeoff validate`

```text
bakeoff validate WORK_ORDER
```

Loads JSON or JSONC, validates schema fields, prints the mode, facet, budgets,
scope policy, providers, and judge, then exits without running providers.

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
writability, and provider auth/session state unless auth probes are skipped.

Flags:

| Flag | Meaning |
| --- | --- |
| `--build` | Run live provider edit probes in temporary workspaces. |
| `--skip-auth-probe` | Skip spendful provider auth probes. |
| `--quiet` | Suppress provider heartbeat lines. |
| `--json` | Emit a parseable JSON readiness report. |

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
| `130` | Interrupted. |

Exit code `3` is a completed Bakeoff handoff. Inspect `decision.json` and
`report.md`; do not treat it as a corrupt ledger.
