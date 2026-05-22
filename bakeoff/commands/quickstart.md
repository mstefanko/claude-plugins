---
description: Check first-run Bakeoff readiness
argument-hint: ""
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff doctor:*), Bash(bakeoff doctor:*)
---

# /bakeoff:quickstart

Use after `/plugin install bakeoff@mstefanko-plugins` and `/bakeoff:setup`.

Apply the shared Bakeoff skill contract. Do not request or write secrets.

## Flow

1. Run:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli" --check
   ```

   If this exits `2`, stop and tell the user:

   ```text
   Run /bakeoff:setup to build the bundled Bakeoff Go CLI into plugin data, or
   set BAKEOFF_GO_BINARY. Go 1.24+ is required for the default setup path.
   ```

2. Run:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" doctor --json --quiet
   ```

   This runs provider auth probes. If the user wants a faster/no-spend check,
   direct them to `/bakeoff:doctor --skip-auth-probe`.

3. Summarize local readiness from the JSON:

   - launcher or binary status from the ensure step;
   - `claude`, `codex`, optional `gemini`/`copilot`, and `git` availability;
   - cwd writability;
   - canonical and selected default provider pair;
   - default provider models;
   - scope controls and any advisory fallback;
   - warnings or missing setup tasks.

4. Surface provider auth/session failures as next actions. Do not ask for API
   keys; tell the user to authenticate with the provider CLI directly.

5. Mention that `/bakeoff:doctor --build` runs the live build readiness probe.

6. End with the next useful command:

   ```text
   /bakeoff:run <request>
   ```

If setup is incomplete, report the action needed: install Go 1.24+ and run
`/bakeoff:setup`, set `BAKEOFF_GO_BINARY` to an executable Bakeoff binary, use
the optional release-binary setup path, or authenticate the provider CLIs
through their normal login flows.
