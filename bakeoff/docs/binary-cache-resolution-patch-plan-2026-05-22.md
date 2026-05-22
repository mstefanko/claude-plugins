# Binary Cache Resolution Patch Plan

## Root Cause Chain

1. A stale cache `dist/bakeoff` binary could survive after source moved on. In
   the observed failure, the cached binary did not include the
   `ledger.UpdateLatest` per-call temp path fix that uses
   `MkdirTemp(outDir, ".latest.*.tmp")`.
2. `bakeoff_candidate_binaries` only considered plugin-data binaries when the
   caller supplied `BAKEOFF_PLUGIN_DATA` or `CLAUDE_PLUGIN_DATA`. Sessions
   without those variables fell through to cache `dist/bakeoff`, even when the
   conventional Claude plugin data binary existed.
3. Parallel launch helpers could hardcode cache or wrapper paths. That bypassed
   the intended resolver and made the stale binary win regardless of environment
   fixes.

## Patch Plan

1. Resolve binaries through one shared candidate list:
   - `BAKEOFF_GO_BINARY`
   - `BAKEOFF_PLUGIN_DATA/bin/bakeoff`
   - `CLAUDE_PLUGIN_DATA/bin/bakeoff`
   - `<plugins-root>/data/<plugin>-<marketplace>/bin/bakeoff`
   - `dist/bakeoff` as the final packaged/source-checkout fallback

   Resolution is order-only. The resolver does not compare mtimes, hashes, or
   version strings to break ties; a data-dir candidate always beats
   `dist/bakeoff` when both exist.

   Conventional Claude plugin data is derived only from recognized Claude
   plugin roots:

   ```text
   <plugins-root>/marketplaces/<marketplace>/<plugin>
   <plugins-root>/cache/<marketplace>/<plugin>/<version>
   ```

   For either root form, the conventional data binary is exactly:

   ```text
   <plugins-root>/data/<plugin>-<marketplace>/bin/bakeoff
   ```

   Example:

   ```text
   ~/.claude/plugins/marketplaces/mstefanko-plugins/bakeoff
   -> ~/.claude/plugins/data/bakeoff-mstefanko-plugins/bin/bakeoff
   ```

2. After a successful setup install into plugin data and a successful version
   probe of the new binary, delete root `dist/bakeoff` outright with `rm -f`.
   No sentinel, rename, or freshness marker is used. A missing cache binary then
   means "post-setup; use data dir."

3. Give launchers a stable path contract. `scripts/bakeoff-ensure-cli --check
   --print-path` prints the resolved executable path only; `/bakeoff:run`
   captures that path once as `BAKEOFF_CLI` and uses it for every child
   invocation.

## Ancillary Cleanup

This is not part of the stale-binary root cause, but it touched the same helper
surface: keep local build cache paths configurable. Helpers should use `GOCACHE`
when set and otherwise derive the default from `TMPDIR`.

## Migration Note

After upgrade, `/bakeoff:run` resolves `BAKEOFF_CLI` with
`scripts/bakeoff-ensure-cli --check --print-path`. If a conventional data-dir
binary already exists, the run self-heals and uses it even when plugin data env
vars are missing. If no data-dir binary exists, the user must run
`/bakeoff:setup`; setup installs the data binary and deletes root
`dist/bakeoff`. Already-emitted old launch scripts with hardcoded cache paths
must be regenerated or manually changed to use `BAKEOFF_CLI`.

## Acceptance Checks

- `scripts/bakeoff-ensure-cli --check --print-path` resolves the conventional
  data binary when plugin data env vars are unset.
- With both conventional data binary and `dist/bakeoff` present, and plugin
  data env vars unset, the resolver picks the conventional data binary by
  order. No mtime/hash comparison is involved.
- `/bakeoff:setup --yes` deletes root `dist/bakeoff` after the
  data binary is installed.
- Parallel launcher skeletons use `BAKEOFF_CLI`, not cache `dist/bakeoff`.
- Active scripts have no literal `/tmp/bakeoff-go-cache`; source-build fallback
  defaults derive from `${TMPDIR:-/tmp}` unless `GOCACHE` is set.
- `TestUpdateLatestConcurrent` still covers in-process latest updates.
- `TestUpdateLatestConcurrentCLIResearch` launches multiple real
  `bakeoff research` processes against one shared `--out`, and every process
  succeeds without leftover `.latest.*.tmp` artifacts.
