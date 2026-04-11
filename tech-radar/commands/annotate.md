---
description: "Add annotations (approve/reject/bookmark) to repos"
argument-hint: "<repo-name> <status> [--notes 'text'] [--reason 'why']"
---

# Tech Radar Annotate

Add annotations to repos in the database. Annotations persist across scans and influence future `needs_verdict` decisions — rejected repos won't be re-evaluated.

## Usage

```
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar annotate <full_name> <status> [--note "reason"]
```

- `<full_name>`: GitHub repo in `owner/repo` format
- `<status>`: One of `watching`, `tested`, `adopted`, `rejected`, `archived`
- `--notes`: Optional free-text notes
- `--reason`: Optional rejection reason (used with `rejected` status)

## Examples

```bash
# Watch a repo you want to track
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar annotate rails/rails watching --notes "Core framework"

# Mark as adopted
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar annotate hotwired/turbo-rails adopted --notes "Using in myorthomd-web"

# Reject a repo to skip future evaluations
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar annotate some/spam rejected --reason "Not relevant to our stack"

# Archive a repo you've moved on from
$CLAUDE_PLUGIN_ROOT/scripts/tech-radar annotate old/tool archived --notes "Replaced by new/tool"
```

Annotations can also be managed interactively via `/tech-radar:dashboard`.
