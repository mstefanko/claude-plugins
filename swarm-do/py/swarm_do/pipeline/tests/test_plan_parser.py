from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.plan import parse_plan


class PlanParserTests(unittest.TestCase):
    def test_parse_phase_heading_tags_and_files(self) -> None:
        text = """# Plan

### Phase 1: Parser work (complexity: moderate, kind: feature)

Files affected
- py/swarm_do/pipeline/plan.py
- py/swarm_do/pipeline/cli.py

- Add parser.
- Add CLI.
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.md"
            path.write_text(text, encoding="utf-8")
            phases = parse_plan(path)
        self.assertEqual(len(phases), 1)
        self.assertEqual(phases[0].phase_id, "1")
        self.assertEqual(phases[0].complexity, "moderate")
        self.assertEqual(phases[0].kind, "feature")
        self.assertIn("py/swarm_do/pipeline/plan.py", phases[0].explicit_files)
        self.assertGreaterEqual(phases[0].implementation_bullets, 2)

    def test_plan_without_phase_headings_becomes_single_inferred_phase(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "scratch.md"
            path.write_text("- Update `README.md`.\n", encoding="utf-8")
            phases = parse_plan(path)
        self.assertEqual(len(phases), 1)
        self.assertEqual(phases[0].phase_id, "plan")
        self.assertEqual(phases[0].referenced_files, ["README.md"])


if __name__ == "__main__":
    unittest.main()
