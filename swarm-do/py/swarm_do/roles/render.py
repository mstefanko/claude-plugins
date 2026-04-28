"""Role-spec renderers.

Converts a RoleSpec into the generated file formats:
  to_agents_md(spec)        — renders agents/agent-<name>.md (stamp + frontmatter + body).
  to_shared_md(spec)        — renders roles/<name>/shared.md (same format, same stamp).
  to_permissions_json(spec) — renders permissions/<short-name>.json for telemetry consumers.

Stamp format: HTML comment on line 1 —
  <!-- generated from role-specs/agent-<name>.md — do not edit; run
       `python3 -m swarm_do.roles gen --write` to update -->
Markdown renderers embed the YAML frontmatter so parse_markdown() can roundtrip.
"""
from __future__ import annotations

import json

from .spec import RoleSpec


def _stamp(spec: RoleSpec) -> str:
    return (
        f"<!-- generated from role-specs/agent-{spec.name[len('agent-'):]}.md"
        f" — do not edit; run `python3 -m swarm_do.roles gen --write` to update -->"
    )


def _frontmatter_block(spec: RoleSpec) -> str:
    """Emit the YAML frontmatter block so parse_markdown can roundtrip."""
    lines = ["---"]
    lines.append(f"name: {spec.name}")
    lines.append(f"description: {spec.description}")
    lines.append("consumers:")
    for c in spec.consumers:
        lines.append(f"  - {c}")
    if spec.tools:
        lines.append("tools:")
        for t in spec.tools:
            lines.append(f"  - {t}")
    if spec.disallowed_tools:
        lines.append("disallowedTools:")
        for t in spec.disallowed_tools:
            lines.append(f"  - {t}")
    lines.append("---")
    return "\n".join(lines) + "\n"


def to_agents_md(spec: RoleSpec) -> str:
    """Render a RoleSpec to agents/agent-<name>.md content.

    Output: stamp + blank line + frontmatter + blank line + body + trailing newline.
    """
    body = spec.body_text
    body = body.rstrip("\n") + "\n"
    return _stamp(spec) + "\n\n" + _frontmatter_block(spec) + "\n" + body


def to_shared_md(spec: RoleSpec) -> str:
    """Render a RoleSpec to roles/<name>/shared.md content.

    Output: stamp + blank line + frontmatter + blank line + body + trailing newline.
    """
    body = spec.body_text
    body = body.rstrip("\n") + "\n"
    return _stamp(spec) + "\n\n" + _frontmatter_block(spec) + "\n" + body


_PERMISSIONS_GENERATED_MARKER = (
    "generated from role-specs/agent-<name>.md — do not edit; run "
    "`python3 -m swarm_do.roles gen --write` to update"
)


def to_permissions_json(spec: RoleSpec) -> str:
    """Render a RoleSpec to permissions/<short-name>.json content.

    Derived artifact for telemetry's permissions_contract reader. Synthesizes
    the legacy schema_version / merge_policy / role fields from the spec.
    """
    short_name = spec.name[len("agent-"):]
    payload = {
        "_generated": _PERMISSIONS_GENERATED_MARKER,
        "schema_version": 1,
        "role": short_name,
        "merge_policy": "deny-wins",
        "permissions": {
            "allow": list(spec.tools),
            "deny": list(spec.disallowed_tools),
        },
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"
