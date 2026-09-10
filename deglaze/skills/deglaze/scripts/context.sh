#!/bin/bash
# Working-tree context injected into SKILL.md via !`${CLAUDE_SKILL_DIR}/scripts/context.sh`.
# Prints nothing outside a git repo. Always exits 0: a non-zero exit would abort the skill.
git diff --stat HEAD 2>/dev/null | tail -n 30
git log --oneline -3 2>/dev/null
exit 0
