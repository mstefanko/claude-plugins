---
description: "Guided first-run bootstrap for SwarmDaddy"
argument-hint: ""
---

# /swarmdaddy:quickstart

Initialize the repo for the shortest successful first run, then open the TUI.

## Execute

Run via Bash:

```bash
set -euo pipefail

if [[ "${SWARMDADDY_QUICKSTART_YES:-0}" != "1" ]]; then
  printf 'quickstart will initialize Beads in this repo (if missing) and migrate any user pipelines into unified presets. Continue? [Y/n] '
  read -r reply
  case "$reply" in
    ""|y|Y|yes|YES) ;;
    *) echo "quickstart cancelled"; exit 0 ;;
  esac
fi

if ! bd where >/dev/null 2>&1; then
  bd init --stealth
fi

"$CLAUDE_PLUGIN_ROOT/bin/swarm" preset migrate

active="$("$CLAUDE_PLUGIN_ROOT/bin/swarm" preset list 2>/dev/null | awk '/^\*/ {print $2; exit}')"
if [[ -z "${active:-}" ]]; then
  load_balanced="yes"
  if [[ "${SWARMDADDY_QUICKSTART_YES:-0}" != "1" ]]; then
    printf 'activate recommended balanced preset for everyday implementation? [Y/n] '
    read -r load_reply
    case "$load_reply" in
      ""|y|Y|yes|YES) load_balanced="yes" ;;
      *) load_balanced="no" ;;
    esac
  fi
  if [[ "$load_balanced" == "yes" ]]; then
    "$CLAUDE_PLUGIN_ROOT/bin/swarm" preset load balanced
    active="balanced"
  fi
fi
providers="unchecked"
printf 'rig: ok | active: %s | providers: %s\n' "${active:-default-fallback}" "$providers"

"$CLAUDE_PLUGIN_ROOT/bin/swarm-tui"
```

Set `SWARMDADDY_QUICKSTART_YES=1` to skip the prompt in non-interactive shells.
