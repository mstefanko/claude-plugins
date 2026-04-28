from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.prepare import STATUS_READY, load_prepared_artifact, prepare_plan_run


class PlanPrepareWriteTests(unittest.TestCase):
    def test_prepare_run_writes_ready_artifact_with_work_units_for_every_phase(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"
            root.mkdir()
            plan = root / "plan.md"
            plan.write_text(
                "### Phase 1: Parser (complexity: moderate, kind: feature)\n\n"
                "### File Targets\n\n"
                "- `py/swarm_do/pipeline/plan.py`\n"
                "- `py/swarm_do/pipeline/cli.py`\n\n"
                "### Acceptance Criteria\n\n"
                "- Parser API is stable.\n"
                "- CLI uses parser output.\n\n"
                "### Verification Commands\n\n"
                "```\npython3 -m unittest discover -s py/swarm_do/pipeline/tests -p 'test_plan*.py'\n```\n",
                encoding="utf-8",
            )
            data = Path(td) / "external-data"

            result = prepare_plan_run("plan.md", repo_root=root, data_dir=data, run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV")

            self.assertEqual(result.status, STATUS_READY)
            self.assertIsNotNone(result.artifact_path)
            loaded = load_prepared_artifact(result.run_id, data_dir=data, repo_root=root)
            self.assertEqual(loaded["status"], STATUS_READY)
            self.assertEqual(set(loaded["work_unit_artifacts"]), {"1"})
            descriptor = loaded["work_unit_artifacts"]["1"]
            self.assertIn("artifact", descriptor)
            self.assertGreaterEqual(len(descriptor["artifact"]["work_units"]), 2)
            self.assertTrue((root / loaded["prepared_plan_path"]).is_file())

            second = prepare_plan_run("plan.md", repo_root=root, data_dir=data, run_id="01ARZ3NDEKTSV4RRFFQ69G5FAV")
            self.assertEqual(second.cache_hits, 1)

    def test_prepare_dry_run_does_not_write_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repo"
            root.mkdir()
            (root / "plan.md").write_text(
                "### Phase 1: Docs (complexity: simple, kind: docs)\n\n"
                "### File Targets\n\n- `README.md`\n\n"
                "### Acceptance Criteria\n\n- README is updated.\n\n"
                "### Verification Commands\n\n```\ntrue\n```\n",
                encoding="utf-8",
            )
            data = Path(td) / "data"

            result = prepare_plan_run("plan.md", repo_root=root, data_dir=data, dry_run=True, write=False)

            self.assertIsNone(result.artifact_path)
            self.assertFalse((data / "runs").exists())
            self.assertEqual(json.loads(json.dumps(result.to_dict()))["status_label"], "READY_FOR_ACCEPTANCE")


if __name__ == "__main__":
    unittest.main()
