---
description: Check Bakeoff provider and host readiness
argument-hint: "[--skip-auth-probe] [--build] [--quiet]"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli:*), Bash(${CLAUDE_PLUGIN_ROOT}/bin/bakeoff doctor:*), Bash(bakeoff doctor:*)
---

# /bakeoff:doctor

Run explicit Bakeoff readiness diagnostics.

Apply the shared Bakeoff skill contract. Do not ask for provider API keys and do
not write secrets into files.

## Flow

1. Run:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-ensure-cli" --check
   ```

   If this exits `2`, tell the user to install Go 1.24+ and run
   `/bakeoff:setup`, set `BAKEOFF_GO_BINARY`, or use the optional
   release-binary setup path. Do not run setup automatically from doctor.

2. Parse `$ARGUMENTS`. Pass through only:

   - `--skip-auth-probe`
   - `--build`
   - `--quiet`

3. Run:

   ```bash
   "${CLAUDE_PLUGIN_ROOT}/bin/bakeoff" doctor --json [passed flags]
   ```

4. Summarize actionable readiness:

   - missing binaries;
   - canonical default pair and any selected fallback pair;
   - provider auth/session failures;
   - sandbox and scope-control readiness;
   - cwd writability;
   - build edit-probe failures when `--build` was passed;
   - warnings and next setup actions.

`--build` is the live build readiness probe. It is a flag on doctor, not a
separate workflow ceremony.
