from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.decompose import (
    build_decompose_diagnostic,
    decompose_plan_phase,
)
from swarm_do.pipeline.plan import parse_plan


def _decompose(plan_text: str, phase_id: str):
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "plan.md"
        path.write_text(plan_text, encoding="utf-8")
        result = decompose_plan_phase(path, phase_id)
        phase = next(phase for phase in parse_plan(path) if phase.phase_id == phase_id)
        return phase, result, path


class DecomposeDiagnosticTests(unittest.TestCase):
    def test_simple_single_unit_diagnostic(self) -> None:
        plan = (
            "### Phase 1: Docs\n\n"
            "Files affected\n- README.md\n\n"
            "- Update `README.md`.\n"
        )
        phase, result, path = _decompose(plan, "1")

        diag = build_decompose_diagnostic(phase, result, plan_path=path)

        self.assertEqual(diag["phase_id"], "1")
        self.assertEqual(diag["complexity"], "simple")
        self.assertEqual(diag["split_decision"], "single")
        self.assertEqual(diag["file_count"], 1)
        self.assertEqual(diag["directory_count"], 1)
        self.assertEqual(diag["cluster_signals"], ["."])
        self.assertEqual(diag["unit_count"], 1)
        self.assertEqual(diag["depends_on"], [{"unit_id": "unit-1", "depends_on": []}])
        self.assertEqual(diag["lint_error_count"], 0)

    def test_split_by_prefix_diagnostic(self) -> None:
        plan = (
            "### Phase 2: Multi (complexity: hard, kind: feature)\n\n"
            "Files affected\n"
            "- py/a/x.py\n"
            "- py/a/y.py\n"
            "- py/b/z.py\n"
            "- docs/README.md\n\n"
            "Acceptance Criteria\n"
            "- Each path is wired up.\n"
        )
        phase, result, path = _decompose(plan, "2")

        diag = build_decompose_diagnostic(phase, result, plan_path=path)

        self.assertIn(diag["complexity"], {"moderate", "hard", "too_large"})
        self.assertEqual(diag["split_decision"], "split-by-prefix")
        self.assertEqual(sorted(diag["cluster_signals"]), ["docs", "py"])
        self.assertGreaterEqual(diag["unit_count"], 2)
        # Default chain: every unit after the first depends on the previous one.
        non_first = [d for d in diag["depends_on"] if d["depends_on"]]
        self.assertTrue(non_first)


if __name__ == "__main__":
    unittest.main()
