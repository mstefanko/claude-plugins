---
name: obsidian-notes
description: >
  USE THIS SKILL when the user says: "record this decision",
  "write a decision record", "document this in obsidian",
  "obsidian decision", "ADR", "decision record", "save a note",
  "note this", "log this", "capture this", "quick note",
  "remember this in obsidian", "search my notes",
  "did I note something about", "check my obsidian",
  "/obsidian-notes". Saves notes and decision records to the
  user's Obsidian vault and searches them.
allowed-tools: "Read,Bash,Write,Grep,Glob"
version: "1.0.0"
author: "mstefanko"
---

# Obsidian Notes

## Overview

One command to save, one to search. Claude decides the note structure.

| Command | Purpose |
|---------|---------|
| `/obsidian-notes:save` | Write a note — Claude picks decision vs freeform |
| `/obsidian-notes:search` | Find notes by keyword, tag, or topic |

## Config

| Setting | Value |
|---------|-------|
| Vault path | `~/Documents/Notes` |
| Notes dir | `Dev/notes` |
| Default project | `enovis-plugins` |

## Save Process

1. Determine note type from conversation context:
   - Alternatives evaluated + choice made → `type: decision`
   - Anything else (gotcha, pattern, discovery) → `type: note`
2. If a bead ID was provided, run `bd show <bead-id>` for context
3. Synthesize from the conversation — do NOT dump raw discussion
4. Generate a filename slug from the title (lowercase, hyphens,
   no special characters). Prefix with today's date: `YYYY-MM-DD-slug.md`
5. Ensure `~/Documents/Notes/Dev/notes/` exists (mkdir -p via Bash)
6. Use the Write tool to create the file
7. Report the file path to the user

## Search Process

1. Parse query and --all flag
2. Default scope: `~/Documents/Notes/Dev/notes/`
   With --all: `~/Documents/Notes/`
3. Use Grep for content search, Glob for file listing
4. Read matches, present as: title, type, date, 1-2 line preview
5. Empty query = list all notes by date

## YAML Frontmatter Safety

ALWAYS wrap the title value in double quotes. Colons, quotes, or
special characters in unquoted titles break Obsidian's YAML parser:

    title: "Use three-step auth instead of single-shot login"     ← CORRECT
    title: Use three-step auth: a better approach                 ← BREAKS YAML

## Format Reference

See [Formats Reference](resources/formats.md) for the complete
frontmatter schema, decision record template, and note examples.

## Quality Rules

### For decisions (`type: decision`)

- [ ] Title is a complete sentence stating the decision (not a topic)
- [ ] Title is wrapped in double quotes in frontmatter
- [ ] Context explains the problem, not the solution
- [ ] "Ruled Out" section lists alternatives with rejection reasons
- [ ] Consequences include both positive and negative impacts
- [ ] No implementation details — those belong in git/beads
- [ ] Under 300 words total

### For notes (`type: note`)

- [ ] Title is a clear, specific statement (not vague like "MySQL issue")
- [ ] Title is wrapped in double quotes in frontmatter
- [ ] Body is concise — capture the insight, not the full story
- [ ] No code blocks longer than 3 lines — point to the file instead
- [ ] Tags are specific enough to find this note later

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Title is a topic ("Auth refactor") | Sentence ("Use three-step auth startup instead of single-shot login") |
| Title is vague ("MySQL thing") | Specific ("MySQL silently truncates strings over 255 chars in legacy columns") |
| Context describes the solution | Context describes the problem |
| No "Ruled Out" in decisions | Always document what you didn't choose |
| Includes code snippets | Point to the commit or file instead |
| Dumping raw conversation | Distill — the note should be shorter than the discussion |
| Unquoted title with colons | Always wrap title in double quotes |
