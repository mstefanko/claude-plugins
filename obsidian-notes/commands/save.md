---
description: Save a note or decision record to your Obsidian vault
argument-hint: "[bead-id or topic]"
---

Save a note to the user's Obsidian vault. Follow the obsidian-notes
skill for format and process.

**First:** Read `~/.obsidian-notes.json` for vault_path and notes_dir.
If the file doesn't exist, tell the user to run
`/obsidian-notes:setup` first and stop.

Ensure the notes directory exists before writing (mkdir -p via Bash).
Check if a file with the same slug already exists — if so, append a
numeric suffix (-2, -3, etc.) to avoid overwriting.

The user is calling this mid-conversation while context is fresh.
Synthesize from what was just discussed.

Decide the note type based on the conversation:
- If alternatives were evaluated and a choice was made → type: decision
  (structured: Context, Decision, Ruled Out, Consequences)
- Otherwise → type: note (freeform body, whatever structure fits)

Detect the project name from the current git repo:
`basename $(git rev-parse --show-toplevel 2>/dev/null)`
If not in a git repo, fall back to the `project` value from config.

If the argument looks like a bead ID (beads-xxx), run `bd show <bead-id>`
to pull in additional context. Otherwise, treat the argument as a topic
hint for what to capture.

If no argument and the conversation doesn't make it obvious what to
capture, ask the user what they want to save.
