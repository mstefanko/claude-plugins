---
description: Configure your Obsidian vault for obsidian-notes
argument-hint: ""
---

Set up obsidian-notes by detecting or choosing your Obsidian vault
and configuring where notes are stored.

## Process

1. **Auto-detect vaults** by reading Obsidian's config:
   ```bash
   cat ~/Library/Application\ Support/obsidian/obsidian.json
   ```
   Parse the JSON to extract vault paths from the `vaults` object
   (each value has a `path` field).

2. **If one vault found:** Confirm it with the user.
   **If multiple vaults found:** List them numbered and ask the user
   to pick which one to use for notes.
   **If none found:** Ask the user to provide their vault path manually.

3. **Ask for notes subdirectory.** Suggest `Dev/notes` as default.
   The user can accept or specify a different path within the vault.

4. **Ask for default project name.** This is the `project` field in
   frontmatter. Suggest the current working directory's repo name.

5. **Write config** to `~/.obsidian-notes.json`:
   ```json
   {
     "vault_path": "/Users/example/Documents/Notes",
     "notes_dir": "Dev/notes",
     "project": "my-project"
   }
   ```

6. **Create the notes directory** if it doesn't exist:
   ```bash
   mkdir -p <vault_path>/<notes_dir>
   ```

7. **Confirm setup** by printing the config and the full path where
   notes will be saved.

If `~/.obsidian-notes.json` already exists, show the current config
and ask if the user wants to reconfigure.
