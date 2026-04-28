"""Map permission fragments to telemetry tool-category contracts.

A role's permission fragment (``swarm-do/permissions/<role>.json``) declares
which Claude tools the role is allowed to use. Telemetry observations record
attempted tool calls bucketed into ``tool_category_counts``. This module joins
the two so we can compute role-contract violations without instrumenting the
runtime — pure post-hoc analysis.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from .registry import PLUGIN_ROOT, resolve_telemetry_dir  # noqa: F401


PERMISSIONS_DIR: Path = PLUGIN_ROOT / "swarm-do" / "permissions"


_TOOL_TO_CATEGORY: dict[str, str] = {
    "read": "read",
    "edit": "edit",
    "write": "edit",
    "multiedit": "edit",
    "notebookedit": "edit",
    "applypatch": "edit",
    "apply_patch": "edit",
    "grep": "search",
    "glob": "search",
    "webfetch": "web",
    "websearch": "web",
    "skill": "skill",
}


_BASH_PATTERN_CATEGORIES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^bd(\b|:)"), "shell-bd"),
    (re.compile(r"^git(\b|:)"), "shell-git"),
    (re.compile(r"^rg(\b|:)"), "shell-rg"),
    (re.compile(r"^(grep|ag|fd|find)(\b|:)"), "search"),
    (re.compile(r"^(cat|head|tail|ls|sed|nl|wc|less|stat|tree|jq)(\b|:)"), "read"),
    (re.compile(r"^(pytest|go\s*test|cargo\s*test|rspec|npm\s*test|jest|vitest|bats|ctest|mvn\s*test|gradle\s*test)"), "shell-test"),
    (re.compile(r"^python3?(\b|:)"), "shell-test"),
    (re.compile(r"^(prettier|gofmt|rustfmt|ruff|cp|mv|touch)(\b|:)"), "edit"),
]


def load_permission_fragment(role: str) -> dict[str, Any] | None:
    """Return the parsed fragment for ``role`` (e.g. 'writer'), or None."""

    canonical = role.replace("agent-", "", 1) if role.startswith("agent-") else role
    path = PERMISSIONS_DIR / f"{canonical}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, Mapping):
        return None
    return dict(data)


def _entry_to_category(entry: str) -> str | None:
    """Map a Claude permission entry (e.g. 'Read', 'Bash(rg:*)') to a category.

    Returns None when the entry cannot be mapped — the caller treats unmapped
    entries as opaque and flags any usage outside of declared categories
    separately.
    """

    e = entry.strip()
    lowered = e.lower()
    if lowered in _TOOL_TO_CATEGORY:
        return _TOOL_TO_CATEGORY[lowered]
    bash_match = re.match(r"^bash\((.+)\)$", lowered)
    if bash_match:
        spec = bash_match.group(1).strip()
        for pattern, category in _BASH_PATTERN_CATEGORIES:
            if pattern.search(spec):
                return category
        return None
    return None


def derive_allowed_categories(fragment: Mapping[str, Any]) -> set[str]:
    perms = fragment.get("permissions") or {}
    allow = perms.get("allow") if isinstance(perms, Mapping) else None
    if not isinstance(allow, list):
        return set()
    categories: set[str] = set()
    for entry in allow:
        if not isinstance(entry, str):
            continue
        category = _entry_to_category(entry)
        if category:
            categories.add(category)
    return categories


def derive_denied_categories(fragment: Mapping[str, Any]) -> set[str]:
    perms = fragment.get("permissions") or {}
    deny = perms.get("deny") if isinstance(perms, Mapping) else None
    if not isinstance(deny, list):
        return set()
    categories: set[str] = set()
    for entry in deny:
        if not isinstance(entry, str):
            continue
        category = _entry_to_category(entry)
        if category:
            categories.add(category)
    return categories


def compute_contract_usage(
    role: str,
    tool_category_counts: Mapping[str, int],
    *,
    fragment: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare observed tool-category usage to the role's permission contract.

    Violations are categories that were used (count > 0) but are either:
    - explicitly in the deny set, or
    - missing from a non-empty allow set.

    A role with no fragment yields ``{"unknown_contract": True, ...}`` so the
    caller can decide whether to surface the row.
    """

    fragment = fragment if fragment is not None else load_permission_fragment(role)
    if fragment is None:
        return {
            "role": role,
            "unknown_contract": True,
            "allowed_categories": [],
            "denied_categories": [],
            "violations": [],
            "used_categories": dict(tool_category_counts or {}),
        }

    allowed = derive_allowed_categories(fragment)
    denied = derive_denied_categories(fragment)
    used = {
        category: count
        for category, count in (tool_category_counts or {}).items()
        if isinstance(count, int) and count > 0
    }

    violations: list[dict[str, Any]] = []
    for category, count in sorted(used.items()):
        if category in denied:
            violations.append({"category": category, "count": count, "reason": "denied"})
        elif allowed and category not in allowed:
            violations.append({"category": category, "count": count, "reason": "not_allowed"})

    return {
        "role": role,
        "unknown_contract": False,
        "allowed_categories": sorted(allowed),
        "denied_categories": sorted(denied),
        "used_categories": used,
        "violations": violations,
    }
