"""Tests for swarm_do.roles.spec — frontmatter parser and validator."""
from __future__ import annotations

import textwrap
import unittest
from pathlib import Path

from swarm_do.roles.spec import RoleSpec, _parse_frontmatter, load, validate


class TestParseFrontmatter(unittest.TestCase):

    def test_simple_scalar_fields(self) -> None:
        text = textwrap.dedent("""\
            ---
            name: agent-foo
            description: A test agent.
            consumers:
              - agents
            ---
            Body here.
        """)
        fields, body = _parse_frontmatter(text)
        self.assertEqual(fields["name"], "agent-foo")
        self.assertEqual(fields["description"], "A test agent.")
        self.assertIn("agents", fields["consumers"])
        self.assertIn("Body here.", body)

    def test_missing_opening_delimiter_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_frontmatter("no frontmatter here")

    def test_missing_closing_delimiter_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_frontmatter("---\nname: agent-x\n")

    def test_multiple_consumers(self) -> None:
        text = textwrap.dedent("""\
            ---
            name: agent-review
            description: Reviewer.
            consumers:
              - agents
              - roles-shared
            ---
            body
        """)
        fields, _ = _parse_frontmatter(text)
        self.assertIn("agents", fields["consumers"])
        self.assertIn("roles-shared", fields["consumers"])

    def test_comment_lines_ignored(self) -> None:
        text = textwrap.dedent("""\
            ---
            name: agent-bar
            description: Bar.
            consumers:
              - agents
              # this is a comment
            ---
            body
        """)
        # Should not raise
        fields, _ = _parse_frontmatter(text)
        self.assertEqual(fields["name"], "agent-bar")

    def test_inline_comment_stripped(self) -> None:
        text = textwrap.dedent("""\
            ---
            name: agent-baz
            description: Baz.
            consumers:
              - agents
              # or agents + roles-shared
            ---
            body
        """)
        fields, _ = _parse_frontmatter(text)
        self.assertEqual(fields["name"], "agent-baz")


class TestLoad(unittest.TestCase):

    def _make_spec_file(self, tmp_path: Path, name: str, body: str = "body\n") -> Path:
        content = textwrap.dedent(f"""\
            ---
            name: {name}
            description: Test description.
            consumers:
              - agents
            ---
            {body}""")
        p = tmp_path / f"{name}.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_load_valid_spec(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            path = self._make_spec_file(tmp, "agent-foo")
            spec = load(path)
            self.assertEqual(spec.name, "agent-foo")
            self.assertEqual(spec.consumers, ("agents",))

    def test_load_filename_mismatch_raises(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            # file named agent-bar but name: agent-foo inside
            content = textwrap.dedent("""\
                ---
                name: agent-foo
                description: Desc.
                consumers:
                  - agents
                ---
                body
            """)
            path = tmp / "agent-bar.md"
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                load(path)

    def test_load_missing_name_raises(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            tmp = Path(d)
            content = textwrap.dedent("""\
                ---
                description: Desc.
                consumers:
                  - agents
                ---
                body
            """)
            path = tmp / "agent-foo.md"
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                load(path)


class TestValidate(unittest.TestCase):

    def _spec(self, **kwargs: object) -> RoleSpec:
        defaults = dict(
            name="agent-foo",
            description="A test agent.",
            consumers=("agents",),
            body_text="body\n",
        )
        defaults.update(kwargs)
        return RoleSpec(**defaults)  # type: ignore[arg-type]

    def test_valid_name_passes(self) -> None:
        validate(self._spec(name="agent-foo-bar"))

    def test_name_without_agent_prefix_fails(self) -> None:
        with self.assertRaises(ValueError):
            validate(self._spec(name="foo-bar"))

    def test_unknown_consumer_fails(self) -> None:
        with self.assertRaises(ValueError):
            validate(self._spec(consumers=("unknown-consumer",)))

    def test_empty_consumers_fails(self) -> None:
        with self.assertRaises(ValueError):
            validate(self._spec(consumers=()))

    def test_roles_shared_consumer_valid(self) -> None:
        validate(self._spec(consumers=("agents", "roles-shared")))

    def test_filename_mismatch_fails(self) -> None:
        spec = self._spec(name="agent-foo")
        with self.assertRaises(ValueError):
            validate(spec, path=Path("agent-bar.md"))


if __name__ == "__main__":
    unittest.main()
