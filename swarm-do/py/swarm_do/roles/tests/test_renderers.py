"""Tests for swarm_do.roles.render."""
from __future__ import annotations

import unittest
from pathlib import Path

from swarm_do.roles.render import to_agents_md, to_shared_md
from swarm_do.roles.spec import RoleSpec, load

_STAMP_PREFIX = "<!-- generated from role-specs/"


def _make_spec(
    name: str = "agent-foo",
    consumers: tuple[str, ...] = ("agents",),
    body: str = "# Role: agent-foo\n\nSome content here.\n",
) -> RoleSpec:
    return RoleSpec(
        name=name,
        description="Test description.",
        consumers=consumers,
        body_text=body,
    )


def _find_role_specs_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "swarm-do" / "role-specs"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("Could not locate swarm-do/role-specs/")


class TestToAgentsMd(unittest.TestCase):

    def test_stamp_present(self) -> None:
        spec = _make_spec()
        result = to_agents_md(spec)
        self.assertTrue(
            result.startswith(_STAMP_PREFIX),
            f"Expected stamp prefix, got: {result[:80]!r}",
        )

    def test_trailing_newline(self) -> None:
        spec = _make_spec()
        result = to_agents_md(spec)
        self.assertTrue(result.endswith("\n"), "Output must end with newline")

    def test_stamp_contains_spec_name(self) -> None:
        spec = _make_spec(name="agent-bar")
        result = to_agents_md(spec)
        self.assertIn("agent-bar.md", result.splitlines()[0])

    def test_body_preserved(self) -> None:
        body = "# Role: agent-foo\n\nSpecific content.\n"
        spec = _make_spec(body=body)
        result = to_agents_md(spec)
        self.assertIn("Specific content.", result)

    def test_blank_line_between_stamp_and_body(self) -> None:
        spec = _make_spec()
        lines = to_agents_md(spec).splitlines()
        # lines[0] = stamp, lines[1] = blank, lines[2+] = body
        self.assertEqual(lines[1], "", f"Expected blank line after stamp, got: {lines[1]!r}")

    def test_body_without_trailing_newline_gets_one(self) -> None:
        spec = _make_spec(body="body without newline")
        result = to_agents_md(spec)
        self.assertTrue(result.endswith("\n"))


class TestToSharedMd(unittest.TestCase):

    def test_stamp_present(self) -> None:
        spec = _make_spec(name="agent-review", consumers=("agents", "roles-shared"))
        result = to_shared_md(spec)
        self.assertTrue(result.startswith(_STAMP_PREFIX))

    def test_trailing_newline(self) -> None:
        spec = _make_spec(name="agent-review", consumers=("agents", "roles-shared"))
        result = to_shared_md(spec)
        self.assertTrue(result.endswith("\n"))

    def test_same_structure_as_agents_md(self) -> None:
        spec = _make_spec(name="agent-writer", consumers=("agents", "roles-shared"))
        agents = to_agents_md(spec)
        shared = to_shared_md(spec)
        self.assertEqual(agents, shared, "to_agents_md and to_shared_md should produce identical output")

    def test_plan_role_specs_render_to_agents_and_shared(self) -> None:
        specs_dir = _find_role_specs_dir()
        for name in ("agent-plan-review", "agent-plan-normalizer"):
            with self.subTest(name=name):
                spec = load(specs_dir / f"{name}.md")
                self.assertEqual(spec.consumers, ("agents", "roles-shared"))
                self.assertIn("generated from role-specs", to_agents_md(spec))
                self.assertIn("generated from role-specs", to_shared_md(spec))

    def test_analysis_spec_records_notes_only_default(self) -> None:
        spec = load(_find_role_specs_dir() / "agent-analysis.md")
        rendered = to_agents_md(spec)
        self.assertIn("NEEDS_RESEARCH", rendered)
        self.assertIn("context_policy: source_allowed", rendered)
        self.assertIn("do not emit schema-strict `work_units.v2`", rendered)


if __name__ == "__main__":
    unittest.main()
