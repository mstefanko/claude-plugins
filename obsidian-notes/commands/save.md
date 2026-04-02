---
description: Save a note or decision record to your Obsidian vault
argument-hint: "[bead-id or topic]"
---

Save a note to the user's Obsidian vault. Follow the obsidian-notes
skill for format and process.

The user is calling this mid-conversation while context is fresh.
Synthesize from what was just discussed.

Decide the note type based on the conversation:
- If alternatives were evaluated and a choice was made → type: decision
  (structured: Context, Decision, Ruled Out, Consequences)
- Otherwise → type: note (freeform body, whatever structure fits)

If the argument looks like a bead ID (beads-xxx), run `bd show <bead-id>`
to pull in additional context. Otherwise, treat the argument as a topic
hint for what to capture.

If no argument and the conversation doesn't make it obvious what to
capture, ask the user what they want to save.
