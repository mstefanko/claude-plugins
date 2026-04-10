---
description: "Add annotations (approve/reject/bookmark) to repos"
argument-hint: "<repo-name> <status> [--note 'reason']"
---

# Tech Radar Annotate

Add annotations to repos in the database. Annotations persist across scans and influence future `needs_verdict` decisions — rejected repos won't be re-evaluated.

## Usage

```
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar annotate <full_name> <status> [--note "reason"]
```

- `<full_name>`: GitHub repo in `owner/repo` format
- `<status>`: One of `approved`, `rejected`, `bookmarked`
- `--note`: Optional reason for the annotation

## Examples

```bash
# Approve a repo you want to track
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar annotate rails/rails approved --note "Core framework"

# Reject a repo to skip future evaluations
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar annotate some/spam rejected --note "Not relevant"

# Bookmark for later review
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar annotate cool/tool bookmarked --note "Check after v2 release"
```

Annotations can also be managed interactively via `/tech-radar:dashboard`.
