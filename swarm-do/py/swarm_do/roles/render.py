"""Role-spec renderers — skeleton (full implementation in phase-5/2)."""
from __future__ import annotations

from .spec import RoleSpec


def to_agents_md(spec: RoleSpec) -> str:
    """Render a RoleSpec to agents/agent-<name>.md content.

    Output: stamp + blank line + body + trailing newline.
    Raises NotImplementedError until phase-5/2 implementation.
    """
    raise NotImplementedError("to_agents_md() — implemented in phase-5/2")


def to_shared_md(spec: RoleSpec) -> str:
    """Render a RoleSpec to roles/<name>/shared.md content.

    Output: stamp + blank line + body + trailing newline.
    Raises NotImplementedError until phase-5/2 implementation.
    """
    raise NotImplementedError("to_shared_md() — implemented in phase-5/2")
