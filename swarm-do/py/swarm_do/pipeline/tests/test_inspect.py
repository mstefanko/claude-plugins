from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.plan import inspect_plan, write_inspect_run


class InspectTests(unittest.TestCase):
    def test_explicit_complexity_wins(self) -> None:
        text = """### Phase 1: Tiny docs (complexity: hard, kind: docs)

- Update `README.md`.
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.md"
            path.write_text(text, encoding="utf-8")
            reports = inspect_plan(path)
        self.assertEqual(reports[0].complexity, "hard")
        self.assertEqual(reports[0].complexity_source, "explicit")
        self.assertTrue(reports[0].requires_decomposition)

    def test_inferred_simple_when_scope_is_small(self) -> None:
        # Explicit File Targets section required after AC6 (no fallback to
        # `referenced_files` for inspect_phase.file_paths).
        text = """### Phase 1: Tiny docs

Files affected
- README.md

- Update `README.md`.
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.md"
            path.write_text(text, encoding="utf-8")
            reports = inspect_plan(path)
        self.assertEqual(reports[0].complexity, "simple")
        self.assertEqual(reports[0].complexity_source, "inferred")
        self.assertFalse(reports[0].requires_decomposition)

    def test_write_inspect_run_records_prepared_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "data"
            plan = Path(td) / "plan.md"
            plan.write_text("### Phase 1: Tiny\n- Update `README.md`.\n", encoding="utf-8")
            reports = inspect_plan(plan)
            payload = write_inspect_run(plan, reports, data_dir=data, run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV", bd_epic_id="bd-1")
            self.assertTrue(Path(payload["inspect_path"]).is_file())
            self.assertTrue((data / "runs" / "index.jsonl").is_file())
            self.assertIn('"status":"prepared"', (data / "runs" / "index.jsonl").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
