---
description: Install or update the Bakeoff CLI binary
argument-hint: "[--version vX.Y.Z] [--yes]"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-setup:*), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff doctor:*)
---

# /bakeoff:setup

Install the released Bakeoff CLI into persistent plugin data. Apply the shared
Bakeoff skill contract. Do not request or write provider API keys, mutate
project files, or run live build probes.

## Flow

1. Parse `$ARGUMENTS`. Pass through only:

   - `--version <tag>` or `--version=<tag>`
   - `--yes`

2. Run a dry run first:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-setup" --dry-run --json [--version <tag>]
   ```

3. Summarize the selected version, platform, target path, checksum URL, and
   release URL from the JSON.

4. If the user did not pass `--yes`, ask for explicit approval before
   downloading or installing anything.

5. Run:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-setup" --yes [--version <tag>]
   ```

6. Run:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli" --check
   ```

7. Run:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" doctor --skip-auth-probe --json
   ```

8. Summarize readiness and say that full runs still depend on authenticated
   `claude` and `codex` provider CLIs.
