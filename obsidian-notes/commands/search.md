---
description: Search your Obsidian vault notes
argument-hint: "<query> [--all]"
---

Search the user's Obsidian vault for notes matching the query.

**Default scope:** `~/Documents/Notes/Dev/notes/` (Claude Code notes only)
**With --all flag:** `~/Documents/Notes/` (entire vault)

Process:
1. Parse the query and --all flag from the argument
2. Use Grep to search file contents in the target directory
3. For tag searches (e.g. "tags:playwright"), search frontmatter
4. Read matching files
5. Present results as a list: title, type, date, and a 1-2 line
   preview of the content

If no matches found, say so. Don't suggest creating a note — the user
is searching, not writing.

If the query is empty, list all notes in the target directory sorted
by date (most recent first), showing title and type for each.
