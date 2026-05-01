#!/usr/bin/env python3
"""Captured legacy helper: update git_base_sha in prepared_plan.v1.json only."""
import json
import subprocess
from pathlib import Path

run_id = "01KQF2CF61YV7SYVREEWRE4GFB"
repo = Path("/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins/swarm-do")
plan_path = Path.home() / f".local/share/swarmdaddy/runs/{run_id}/prepared_plan.v1.json"
backup = plan_path.with_suffix(".json.bak-before-git-base-refresh")

head = subprocess.check_output(
    ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
).strip()
print(f"HEAD: {head}")

plan = json.loads(plan_path.read_text())
backup.write_text(json.dumps(plan, indent=2, sort_keys=True))
print(f"backup -> {backup}")


def replace_git_base(node: object, new_sha: str) -> int:
    count = 0
    if isinstance(node, dict):
        for k, v in list(node.items()):
            if k == "git_base_sha" and isinstance(v, str):
                if v != new_sha:
                    node[k] = new_sha
                    count += 1
            else:
                count += replace_git_base(v, new_sha)
    elif isinstance(node, list):
        for item in node:
            count += replace_git_base(item, new_sha)
    return count


changed = replace_git_base(plan, head)
print(f"updated {changed} git_base_sha occurrences")

plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
print(f"wrote -> {plan_path}")
