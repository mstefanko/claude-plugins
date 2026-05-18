---
description: Check first-run Bakeoff readiness
argument-hint: ""
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff doctor:*), Bash(bakeoff doctor:*)
---

# /bakeoff:quickstart

Use after `/plugin install bakeoff@mstefanko-plugins`.

Apply the shared Bakeoff skill contract. Do not request or write secrets.

## Flow

1. Run:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli"
   ```

2. Run:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" doctor --skip-auth-probe --json
   ```

3. Summarize local readiness from the JSON:

   - launcher or binary status from the ensure step;
   - `claude`, `codex`, and `git` availability;
   - cwd writability;
   - default Claude and Codex models;
   - scope controls and any advisory fallback;
   - warnings or missing setup tasks.

4. If auth probes were skipped, say that full runs still depend on normal
   provider CLI login/session state.

5. Mention that `/bakeoff:doctor --build` runs the live build readiness probe.

6. End with the next useful command:

   ```text
   /bakeoff:run <request>
   ```

If setup is incomplete, report the action needed: install Go, install a package
that includes `dist/bakeoff`, set `BAKEOFF_GO_BINARY` to an executable Bakeoff
binary, or authenticate the provider CLIs through their normal login flows.
