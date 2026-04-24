"""Role-spec parser and validator — skeleton (full implementation in phase-5/2)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RoleSpec:
    name: str
    description: str
    consumers: tuple[str, ...]
    body_text: str


def load(path: Path) -> RoleSpec:
    """Read a role-spec file and return a RoleSpec.

    Raises NotImplementedError until phase-5/2 implementation.
    """
    raise NotImplementedError("load() — implemented in phase-5/2")


def validate(spec: RoleSpec) -> None:
    """Validate a RoleSpec.

    Raises NotImplementedError until phase-5/2 implementation.
    """
    raise NotImplementedError("validate() — implemented in phase-5/2")


def parse_markdown(text: str) -> RoleSpec:
    """Parse a rendered agent/shared markdown file back into a RoleSpec.

    Used for roundtrip tests. Raises NotImplementedError until phase-5/2.
    """
    raise NotImplementedError("parse_markdown() — implemented in phase-5/2")
