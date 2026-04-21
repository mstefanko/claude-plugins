---
description: "Initialize a stealth beads rig in the current repo (idempotent, explicit)"
argument-hint: ""
---

# /swarm-do:init-beads

Explicit helper for bootstrapping a beads rig so `/swarm-do:do` can run in this repo. **Never auto-invoked.** The swarm pipeline enforces the `bd where` precondition but never creates a rig itself — this command is the supported path when the operator decides a repo should get one.

## Execute

Run these steps in order. Stop on any error and surface it to the operator.

1. **Verify `bd` is on PATH:**
   ```bash
   command -v bd >/dev/null 2>&1 || { echo "bd CLI not on PATH — install beads first" >&2; exit 1; }
   ```

2. **Check for an existing rig (idempotent no-op):**
   ```bash
   if rig="$(bd where 2>/dev/null)" && [[ -n "$rig" ]]; then
     echo "beads rig already present: $rig"
     echo "nothing to do — /swarm-do:do will use this rig"
     exit 0
   fi
   ```

3. **Initialize a stealth rig in the current working directory:**
   ```bash
   bd init --stealth
   ```

4. **Verify:**
   ```bash
   bd where
   ```

## What `--stealth` gives you

A repo-local `.beads/` directory containing a sqlite db. The `--stealth` flag tells `bd` to manage its own `.gitignore` entries so the db and its wal/shm files don't land in git. Exact gitignore content is `bd`'s responsibility — do not hand-edit it.

## What this command does NOT do

- Does **not** auto-run from any hook.
- Does **not** run from a subagent.
- Does **not** touch rigs in other directories.
- Does **not** migrate data — it's a pure `bd init`.

If the repo already has a rig but `bd where` fails (unusual — corrupt or pointing at the wrong dir), fix it manually rather than re-running this. Re-init is not safe on an existing rig.
