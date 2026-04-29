from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.context_bundle import render_context_bundle
from swarm_do.pipeline.tests.phase_session_fixtures import make_prepared_run


class ContextBundleTests(unittest.TestCase):
    def test_dispatcher_bundle_renders_only_requested_phase(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=3)

            result = render_context_bundle(
                run_id=run_id,
                phase_id="2",
                role="dispatcher",
                data_dir=data,
                repo_root=repo,
            )

            context = result["context"]
            prompt = Path(result["prompt_path"]).read_text(encoding="utf-8")
            self.assertEqual(context["phase_id"], "2")
            self.assertEqual(context["phase_index"], 1)
            self.assertIn("Phase 2", prompt)
            self.assertNotIn("Phase 1 acceptance", prompt)
            self.assertNotIn("Phase 3 acceptance", prompt)
            self.assertTrue(Path(result["context_path"]).is_file())
            self.assertFalse((data / "runs" / run_id / "context" / "1").exists())

    def test_writer_bundle_requires_unit_and_records_budget_warning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)

            with self.assertRaises(ValueError):
                render_context_bundle(run_id=run_id, phase_id="1", role="agent-writer", data_dir=data, repo_root=repo)

            result = render_context_bundle(
                run_id=run_id,
                phase_id="1",
                role="agent-writer",
                unit_id="unit-1",
                max_prompt_bytes=800,
                data_dir=data,
                repo_root=repo,
            )

            context = json.loads(Path(result["context_path"]).read_text(encoding="utf-8"))
            self.assertEqual(context["work_unit_id"], "unit-1")
            self.assertIn("context_truncated", context["warnings"])
            self.assertLessEqual(context["prompt_bytes"], context["max_prompt_bytes"])
            self.assertTrue(context["source_list"])


if __name__ == "__main__":
    unittest.main()
