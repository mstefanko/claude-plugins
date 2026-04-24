"""Role-spec parser and validator."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_VALID_CONSUMERS = frozenset({"agents", "roles-shared"})
_NAME_RE = re.compile(r"^agent-[a-z0-9][a-z0-9-]*$")
_STAMP_RE = re.compile(r"^<!-- generated from role-specs/[^\n]+-->\n")


@dataclass(frozen=True)
class RoleSpec:
    name: str
    description: str
    consumers: tuple[str, ...]
    body_text: str


def _parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    """Hand-parse YAML frontmatter (no pyyaml).

    Returns (fields_dict, body_text).
    Raises ValueError on malformed input.
    """
    if not text.startswith("---\n"):
        raise ValueError("Missing opening '---' frontmatter delimiter")

    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("Missing closing '---' frontmatter delimiter")

    fm_block = text[4:end]
    body = text[end + 5:]  # skip "\n---\n"

    fields: dict[str, object] = {}
    current_key: str | None = None
    list_items: list[str] = []

    for line in fm_block.splitlines():
        if line.startswith("  - ") or line.startswith("- "):
            # list item under current_key
            item = line.lstrip("- ").strip()
            if current_key is None:
                raise ValueError(f"List item without key: {line!r}")
            list_items.append(item)
            fields[current_key] = list_items
        elif ": " in line or line.endswith(":"):
            # save previous list
            current_key = None
            list_items = []
            if ": " in line:
                key, _, value = line.partition(": ")
                key = key.strip()
                value = value.strip()
                # strip inline comments
                if " # " in value:
                    value = value[: value.index(" # ")].strip()
                if value:
                    fields[key] = value
                    current_key = key
                else:
                    current_key = key
                    list_items = []
                    fields[key] = list_items
            else:
                key = line.rstrip(":").strip()
                current_key = key
                list_items = []
                fields[key] = list_items
        elif line.strip().startswith("#"):
            # comment line (may be indented) — skip
            pass
        elif line.strip() == "":
            pass
        else:
            raise ValueError(f"Unrecognised frontmatter line: {line!r}")

    return fields, body


def load(path: Path) -> RoleSpec:
    """Read a role-spec file and return a RoleSpec."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        fields, body = _parse_frontmatter(text)
    except ValueError as exc:
        raise ValueError(f"Bad frontmatter in {path}: {exc}") from exc

    name = fields.get("name")
    if not isinstance(name, str):
        raise ValueError(f"Missing or non-string 'name' in {path}")

    description = fields.get("description")
    if not isinstance(description, str):
        raise ValueError(f"Missing or non-string 'description' in {path}")

    raw_consumers = fields.get("consumers", [])
    if not isinstance(raw_consumers, list):
        raise ValueError(f"'consumers' must be a list in {path}")
    consumers: tuple[str, ...] = tuple(str(c) for c in raw_consumers)

    spec = RoleSpec(
        name=name,
        description=description,
        consumers=consumers,
        body_text=body,
    )
    validate(spec, path=path)
    return spec


def validate(spec: RoleSpec, *, path: Path | None = None) -> None:
    """Validate a RoleSpec.

    Raises ValueError with a descriptive message on any violation.
    """
    loc = f" (from {path})" if path else ""

    if not _NAME_RE.match(spec.name):
        raise ValueError(
            f"name {spec.name!r} does not match 'agent-<...>' pattern{loc}"
        )

    unknown = set(spec.consumers) - _VALID_CONSUMERS
    if unknown:
        raise ValueError(
            f"Unknown consumers {unknown!r} — must be subset of "
            f"{sorted(_VALID_CONSUMERS)}{loc}"
        )

    if not spec.consumers:
        raise ValueError(f"consumers list must not be empty{loc}")

    if path is not None:
        expected_stem = f"agent-{spec.name[len('agent-'):]}"
        actual_stem = Path(path).stem
        if actual_stem != spec.name:
            raise ValueError(
                f"Filename stem {actual_stem!r} does not match name {spec.name!r}{loc}"
            )


def parse_markdown(text: str) -> RoleSpec:
    """Parse a rendered agents/shared markdown file back into a RoleSpec.

    Strips the generated stamp, then re-parses the embedded frontmatter
    from body_text. Used for roundtrip tests.

    The rendered file format is:
        <!-- generated from role-specs/agent-<name>.md — do not edit ... -->
        <blank line>
        ---
        name: ...
        ---
        <body>

    We strip the stamp + blank line, then call load() on a temp in-memory
    parse of the remaining YAML+body block.
    """
    # Strip leading stamp if present
    stripped = _STAMP_RE.sub("", text, count=1)
    # Strip optional leading blank line after stamp
    stripped = stripped.lstrip("\n")

    try:
        fields, body = _parse_frontmatter(stripped)
    except ValueError as exc:
        raise ValueError(f"parse_markdown: bad embedded frontmatter: {exc}") from exc

    name = fields.get("name")
    if not isinstance(name, str):
        raise ValueError("parse_markdown: missing 'name' in embedded frontmatter")

    description = fields.get("description", "")
    if not isinstance(description, str):
        description = str(description)

    raw_consumers = fields.get("consumers", [])
    if not isinstance(raw_consumers, list):
        raw_consumers = []
    consumers: tuple[str, ...] = tuple(str(c) for c in raw_consumers)

    # Strip exactly one leading newline that was inserted by the renderer
    # between the frontmatter block and the body.
    if body.startswith("\n"):
        body = body[1:]

    return RoleSpec(
        name=name,
        description=description,
        consumers=consumers,
        body_text=body,
    )
