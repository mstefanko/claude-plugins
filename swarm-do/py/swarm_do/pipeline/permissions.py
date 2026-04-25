"""Role-scoped Claude settings permission presets."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .paths import REPO_ROOT


ROLE_NAMES = {"writer", "spec-review", "review", "research", "clarify", "codex-review", "brainstorm"}
MERGE_POLICIES = {"deny-wins"}


@dataclass(frozen=True)
class PermissionDiff:
    role: str
    missing_allow: list[str]
    missing_deny: list[str]
    conflicts: list[str]

    @property
    def ok(self) -> bool:
        return not self.missing_allow and not self.missing_deny and not self.conflicts


def permission_dir() -> Path:
    return REPO_ROOT / "permissions"


def default_settings_path(scope: str, cwd: Path | None = None) -> Path:
    if scope == "repo":
        return (cwd or Path.cwd()) / ".claude" / "settings.local.json"
    if scope == "user":
        return Path.home() / ".claude" / "settings.local.json"
    raise ValueError("scope must be repo or user")


def load_fragment(role: str) -> dict[str, Any]:
    if role not in ROLE_NAMES:
        raise ValueError(f"unknown permission role: {role}")
    path = permission_dir() / f"{role}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"permission fragment missing: {path}") from exc
    validate_fragment(data, str(path))
    return data


def validate_fragment(data: Mapping[str, Any], label: str = "fragment") -> None:
    if data.get("schema_version") != 1:
        raise ValueError(f"{label}: schema_version must be 1")
    role = data.get("role")
    if role not in ROLE_NAMES:
        raise ValueError(f"{label}: role must be one of {sorted(ROLE_NAMES)}")
    if data.get("merge_policy") not in MERGE_POLICIES:
        raise ValueError(f"{label}: merge_policy must be deny-wins")
    permissions = data.get("permissions")
    if not isinstance(permissions, Mapping):
        raise ValueError(f"{label}: permissions must be an object")
    for key in ("allow", "deny"):
        values = permissions.get(key, [])
        if not isinstance(values, list) or not all(isinstance(value, str) and value for value in values):
            raise ValueError(f"{label}: permissions.{key} must be an array of non-empty strings")


def load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: settings root must be a JSON object")
    return value


def diff_role(settings: Mapping[str, Any], fragment: Mapping[str, Any]) -> PermissionDiff:
    permissions = settings.get("permissions") if isinstance(settings, Mapping) else None
    if not isinstance(permissions, Mapping):
        permissions = {}
    existing_allow = _str_set(permissions.get("allow", []))
    existing_deny = _str_set(permissions.get("deny", []))
    fragment_permissions = fragment["permissions"]
    wanted_allow = _str_set(fragment_permissions.get("allow", []))
    wanted_deny = _str_set(fragment_permissions.get("deny", []))
    conflicts = sorted((wanted_allow & existing_deny) | (wanted_deny & existing_allow))
    return PermissionDiff(
        role=str(fragment["role"]),
        missing_allow=sorted(wanted_allow - existing_allow),
        missing_deny=sorted(wanted_deny - existing_deny),
        conflicts=conflicts,
    )


def merge_role(settings: dict[str, Any], fragment: Mapping[str, Any]) -> dict[str, Any]:
    diff = diff_role(settings, fragment)
    if diff.conflicts:
        raise ValueError(f"{diff.role}: conflicting allow/deny rules: {', '.join(diff.conflicts)}")
    merged = dict(settings)
    permissions = merged.setdefault("permissions", {})
    if not isinstance(permissions, dict):
        raise ValueError("settings.permissions must be an object")
    for key in ("allow", "deny"):
        values = permissions.setdefault(key, [])
        if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
            raise ValueError(f"settings.permissions.{key} must be an array of strings")
        wanted = fragment["permissions"].get(key, [])
        permissions[key] = sorted({*values, *wanted})
    return merged


def uninstall_role(settings: dict[str, Any], fragment: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(settings)
    permissions = merged.get("permissions")
    if not isinstance(permissions, dict):
        return merged
    for key in ("allow", "deny"):
        values = permissions.get(key)
        if isinstance(values, list):
            remove = set(fragment["permissions"].get(key, []))
            permissions[key] = [value for value in values if value not in remove]
    return merged


def format_diff(diff: PermissionDiff) -> str:
    lines = [f"role: {diff.role}"]
    if diff.conflicts:
        lines.append("  conflicts:")
        lines.extend(f"    ! {rule}" for rule in diff.conflicts)
    if diff.missing_allow:
        lines.append("  add permissions.allow:")
        lines.extend(f"    + {rule}" for rule in diff.missing_allow)
    if diff.missing_deny:
        lines.append("  add permissions.deny:")
        lines.extend(f"    + {rule}" for rule in diff.missing_deny)
    if diff.ok:
        lines.append("  ok: no changes needed")
    return "\n".join(lines)


def write_settings_atomic(path: Path, settings: Mapping[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_suffix(path.suffix + ".bak")
    old_mode = None
    if path.exists():
        shutil.copy2(path, backup)
        old_mode = path.stat().st_mode
    text = json.dumps(settings, indent=2, sort_keys=True) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if old_mode is not None:
            os.chmod(tmp, old_mode)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return backup


def _str_set(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {value for value in values if isinstance(value, str)}
