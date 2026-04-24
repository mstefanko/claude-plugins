"""Roundtrip tests: parse(render(load(path))) == load(path) for all 15 specs."""
from __future__ import annotations

import unittest
from pathlib import Path

from swarm_do.roles.render import to_agents_md, to_shared_md
from swarm_do.roles.spec import RoleSpec, load, parse_markdown


def _find_role_specs_dir() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "swarm-do" / "role-specs"
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError("Could not locate swarm-do/role-specs/")


class TestRoundtrip(unittest.TestCase):
    """For each role-spec, verify parse_markdown(to_agents_md(spec)) == spec."""

    @classmethod
    def setUpClass(cls) -> None:
        role_specs_dir = _find_role_specs_dir()
        cls.spec_files = sorted(role_specs_dir.glob("agent-*.md"))

    def test_all_specs_found(self) -> None:
        self.assertGreaterEqual(
            len(self.spec_files),
            15,
            f"Expected at least 15 role-specs, found {len(self.spec_files)}",
        )

    def _roundtrip_one(self, spec_path: Path) -> None:
        """Load spec, render to agents_md, parse back, compare."""
        original = load(spec_path)
        rendered = to_agents_md(original)
        recovered = parse_markdown(rendered)

        self.assertEqual(
            recovered.name,
            original.name,
            f"name mismatch for {spec_path.name}",
        )
        self.assertEqual(
            recovered.description,
            original.description,
            f"description mismatch for {spec_path.name}",
        )
        self.assertEqual(
            recovered.consumers,
            original.consumers,
            f"consumers mismatch for {spec_path.name}",
        )
        # body_text roundtrip: both should end with a single newline
        self.assertEqual(
            recovered.body_text.rstrip("\n"),
            original.body_text.rstrip("\n"),
            f"body_text mismatch for {spec_path.name}",
        )

    def test_roundtrip_all_specs(self) -> None:
        """Parametrized-style: run roundtrip for every spec file."""
        errors: list[str] = []
        for spec_path in self.spec_files:
            try:
                self._roundtrip_one(spec_path)
            except AssertionError as exc:
                errors.append(f"{spec_path.name}: {exc}")
            except Exception as exc:
                errors.append(f"{spec_path.name}: EXCEPTION {exc}")

        if errors:
            self.fail(
                f"Roundtrip failures ({len(errors)}):\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

    def test_shared_roundtrip_for_roles_shared_specs(self) -> None:
        """For specs with roles-shared consumer, also roundtrip via to_shared_md."""
        errors: list[str] = []
        for spec_path in self.spec_files:
            original = load(spec_path)
            if "roles-shared" not in original.consumers:
                continue
            rendered = to_shared_md(original)
            try:
                recovered = parse_markdown(rendered)
                self.assertEqual(
                    recovered.name, original.name,
                    f"shared roundtrip name mismatch for {spec_path.name}",
                )
                self.assertEqual(
                    recovered.body_text.rstrip("\n"),
                    original.body_text.rstrip("\n"),
                    f"shared roundtrip body mismatch for {spec_path.name}",
                )
            except AssertionError as exc:
                errors.append(f"{spec_path.name}: {exc}")

        if errors:
            self.fail(
                f"Shared roundtrip failures:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )


if __name__ == "__main__":
    unittest.main()
