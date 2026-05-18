---
allowed-tools: Bash
description: Remove Bakeoff plugin state and cache
---

# /bakeoff:uninstall

Remove Bakeoff-owned plugin state and cache, then leave the final plugin
uninstall as a manual user step.

Run:

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/bakeoff-uninstall" --force
```

Then tell the user exactly:

```markdown
Plugin data cleaned up. To finish removal, run:
`/plugin uninstall bakeoff@mstefanko-plugins`
```

Do NOT run `/plugin uninstall` automatically.
