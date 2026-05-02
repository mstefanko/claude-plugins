from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.paths import REPO_ROOT
from swarm_do.pipeline.phase_sessions import phase_status
from swarm_do.pipeline.state_projector import diff_mirror, mirror_path_for, project_run
from swarm_do.pipeline.tests.test_state_projector import materialize_fixture


PIPELINE_ROOT = REPO_ROOT / "py" / "swarm_do" / "pipeline"


class StateProjectorDiffTests(unittest.TestCase):
    def test_fresh_projection_has_no_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            run_id = materialize_fixture("retryable-failure-then-success", data_dir)
            project_run(run_id, data_dir=data_dir)

            self.assertEqual([], diff_mirror(run_id, data_dir=data_dir))

    def test_diff_points_to_changed_source_sha(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            run_id = materialize_fixture("clean-single-phase", data_dir)
            project_run(run_id, data_dir=data_dir)
            phase_path = data_dir / "runs" / run_id / "phase_sessions.v1.json"
            payload = json.loads(phase_path.read_text(encoding="utf-8"))
            payload["updated_at"] = "2026-05-02T00:09:00Z"
            phase_path.write_text(json.dumps(payload), encoding="utf-8")

            diffs = diff_mirror(run_id, data_dir=data_dir)

            self.assertEqual("artifact_sources", diffs[0].table)
            self.assertIn(diffs[0].column, {"sha256", "mtime_ns", "size_bytes"})

    def test_corrupt_mirror_does_not_block_phase_status_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            run_id = materialize_fixture("clean-single-phase", data_dir)
            project_run(run_id, data_dir=data_dir)
            mirror_path_for(run_id, data_dir=data_dir).write_bytes(b"not sqlite")

            with self.assertLogs("swarm_do.pipeline.phase_sessions", level="DEBUG") as logs:
                status = phase_status(run_id, data_dir=data_dir)

            self.assertEqual(status["run_id"], run_id)
            self.assertIn("status", status)
            self.assertIn("phase_status mirror read failed", "\n".join(logs.output))

    def test_only_state_projector_writes_mirror_file(self) -> None:
        violations: list[str] = []
        for path in sorted(PIPELINE_ROOT.glob("*.py")):
            if path.name in {"state_projector.py", "cli.py"}:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and node.value == "state.mirror.sqlite":
                    violations.append(f"{path.name}:{node.lineno}")
        self.assertEqual([], violations)


if __name__ == "__main__":
    unittest.main()
