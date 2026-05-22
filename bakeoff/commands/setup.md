---
description: Install or update the Bakeoff CLI binary
argument-hint: "[--yes] [--from-release --version vX.Y.Z]"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-setup:*), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff doctor:*)
---

# /bakeoff:setup

Build the bundled Bakeoff Go CLI into persistent plugin data by default. Apply
the shared Bakeoff skill contract. Do not request or write provider API keys,
mutate project files, or run live build probes.

## Flow

1. Parse `$ARGUMENTS`. Pass through only:

   - `--from-source`
   - `--from-release`
   - `--version <tag>` or `--version=<tag>`
   - `--yes`

2. Run a dry run first:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-setup" --dry-run --json [passed flags except --yes]
   ```

3. Summarize the install kind and target path from the JSON.

   - For `source-build`, say setup will run `go build` against the bundled
     source in `${CLAUDE_PLUGIN_ROOT}` and install the resulting binary under
     `${CLAUDE_PLUGIN_DATA}/bin/bakeoff`. Include the detected Go path/version.
   - For `release-binary`, summarize the selected version, platform, checksum
     URL, and release URL. This is the optional no-Go path and requires a
     published release asset.

4. If the user did not pass `--yes`, ask for explicit approval before
   building or downloading anything.

5. Run:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-setup" --yes [passed flags]
   ```

   If this fails, stop normal setup and summarize the error:

   - If Go is missing or too old, tell the user to install Go 1.24+ and rerun
     `/bakeoff:setup`, or use `BAKEOFF_GO_BINARY` /
     `--from-release --version <tag>` if they want to manage a binary.
   - If a release asset or `checksums.txt` was not found, say the optional
     release-binary path needs a published GitHub Release for that tag. The
     default internal path is `/bakeoff:setup` without `--from-release`.
   - For other setup failures, report the failed prerequisite or verification
     step verbatim and stop.

6. Run:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli" --check
   ```

   Only run this after step 5 succeeds.

7. Run:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" doctor --json --quiet
   ```

   This intentionally runs provider auth probes. Setup is the first-run
   readiness moment, so users should see missing `claude`, `codex`, optional
   `gemini`/`copilot`, `git`, scope support, cwd writability, fallback-pair
   status, or provider auth/session problems before trying `/bakeoff:run`.

   If doctor exits non-zero but emits JSON, summarize the JSON instead of
   treating setup as opaque failure: the CLI install succeeded, but readiness
   needs attention.

8. Summarize readiness:

   - binary install path and source-build/release kind;
   - `claude`, `codex`, optional `gemini`/`copilot`, and `git` availability;
   - canonical and selected default provider pair;
   - provider auth probe status and warnings;
   - scope controls and cwd writability;
   - next fixes for missing tools or auth/session failures.

   Mention that `/bakeoff:doctor --build` runs additional live edit probes for
   build-mode readiness.
