# obsidian-notes

Personal Claude Code plugin for saving notes to an Obsidian vault
and searching them later.

## Setup

1. Create the notes directory:
   ```bash
   mkdir -p ~/Documents/Notes/Dev/notes
   ```

2. Install the plugin:
   ```
   /plugin add ~/.claude/my-plugins/obsidian-notes
   ```

## Usage

Use mid-conversation when you hit something worth keeping.
Don't wait until you're done — capture while the context is fresh.

### Saving notes

Just say it:
- "save this to obsidian"
- "record this decision"
- "log this gotcha"

Or use the slash command:
```
/obsidian-notes:save
/obsidian-notes:save beads-xxx
/obsidian-notes:save MySQL truncation
```

Claude decides the structure — if you just evaluated alternatives,
it writes a decision record (Context, Decision, Ruled Out, Consequences).
Otherwise, it writes a freeform note. You never pick the type.

### Searching notes

```
/obsidian-notes:search auth timeout        # search Dev/notes/ only
/obsidian-notes:search --all MySQL          # search entire vault
/obsidian-notes:search                      # list all notes by date
```

Or just say:
- "did I note something about auth timeouts?"
- "check my obsidian notes for MySQL"
- "search my vault for selfhosting"

## Where notes go

All notes land in `~/Documents/Notes/Dev/notes/` with filenames like
`2026-04-02-three-step-auth.md`. The `type` field in frontmatter
(`decision` or `note`) distinguishes them.

## Optional: Obsidian Templates

To create notes manually in Obsidian, add templates to
`~/Documents/Notes/templates/`:

**Decision template:**

    ---
    title: ""
    type: decision
    status: accepted
    created: YYYY-MM-DD
    project:
    tags: []
    ---

    # Title

    ## Context

    ## Decision

    ## Ruled Out

    ## Consequences

**Note template:**

    ---
    title: ""
    type: note
    created: YYYY-MM-DD
    project:
    tags: []
    ---

    # Title

If using the Templater plugin, replace `YYYY-MM-DD` with
`<% tp.date.now("YYYY-MM-DD") %>` and `# Title` with
`# <% tp.file.title %>`.
