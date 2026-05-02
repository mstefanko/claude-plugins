from __future__ import annotations

import json
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from swarm_do.pipeline.paths import REPO_ROOT
from swarm_do.pipeline.state_projector import mirror_path_for, project_run, query_mirror


FIXTURES = REPO_ROOT / "tests" / "fixtures" / "run-traces"


def materialize_fixture(name: str, data_dir: Path) -> str:
    fixture = FIXTURES / name
    phase_state = json.loads((fixture / "run" / "phase_sessions.v1.json").read_text(encoding="utf-8"))
    run_id = str(phase_state["run_id"])
    shutil.copytree(fixture / "run", data_dir / "runs" / run_id)
    if (fixture / "events.jsonl").is_file():
        (data_dir / "telemetry").mkdir(parents=True, exist_ok=True)
        shutil.copy2(fixture / "events.jsonl", data_dir / "telemetry" / "run_events.jsonl")
    if (fixture / "active-run.json").is_file():
        shutil.copy2(fixture / "active-run.json", data_dir / "active-run.json")
    worktree = fixture / "worktrees" / run_id
    if worktree.is_dir():
        shutil.copytree(worktree, data_dir / "worktrees" / run_id)
    return run_id


class StateProjectorTests(unittest.TestCase):
    def test_clean_fixture_projects_run_phase_attempt_and_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            run_id = materialize_fixture("clean-single-phase", data_dir)

            result = project_run(run_id, data_dir=data_dir)

            self.assertTrue(Path(result.mirror_path).is_file())
            self.assertEqual(result.row_counts["runs"], 1)
            self.assertEqual(result.row_counts["phases"], 1)
            self.assertEqual(result.row_counts["phase_attempts"], 1)
            self.assertGreaterEqual(result.row_counts["artifact_sources"], 4)
            rows = query_mirror(run_id, "SELECT phase_id, attempt, launcher FROM phase_attempts", data_dir=data_dir)
            self.assertEqual(rows, [{"attempt": 1, "launcher": "fake-test", "phase_id": "p1"}])

    def test_missing_optional_evidence_warns_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            run_id = materialize_fixture("clean-single-phase", data_dir)
            evidence = data_dir / "runs" / run_id / "phase_launches" / "p1" / "attempt-1" / "evidence.json"
            evidence.unlink()

            result = project_run(run_id, data_dir=data_dir)

            self.assertGreater(result.warning_count, 0)
            warnings = query_mirror(run_id, "SELECT kind, source FROM projection_warnings ORDER BY warn_seq", data_dir=data_dir)
            self.assertTrue(any(row["kind"] == "missing_optional" and "evidence.json" in str(row["source"]) for row in warnings))

    def test_empty_checkpoint_only_run_projects_zero_phases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            run_id = "01J00000000000000000000999"
            run_dir = data_dir / "runs" / run_id
            run_dir.mkdir(parents=True)
            checkpoint = {
                "schema_version": 1,
                "written_at": "2026-05-02T00:00:00Z",
                "run_id": run_id,
                "status": "incomplete",
            }
            (run_dir / "checkpoint.v1.json").write_text(json.dumps(checkpoint), encoding="utf-8")
            (data_dir / "active-run.json").write_text(json.dumps(checkpoint), encoding="utf-8")

            result = project_run(run_id, data_dir=data_dir)

            self.assertEqual(result.row_counts["runs"], 1)
            self.assertEqual(result.row_counts["phases"], 0)
            self.assertEqual(result.row_counts["phase_attempts"], 0)
            self.assertTrue(mirror_path_for(run_id, data_dir=data_dir).is_file())

    def test_unknown_phase_session_schema_is_warning_and_skips_phase_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            run_id = materialize_fixture("clean-single-phase", data_dir)
            phase_path = data_dir / "runs" / run_id / "phase_sessions.v1.json"
            payload = json.loads(phase_path.read_text(encoding="utf-8"))
            payload["schema_version"] = 999
            phase_path.write_text(json.dumps(payload), encoding="utf-8")

            result = project_run(run_id, data_dir=data_dir)

            self.assertEqual(result.row_counts["phases"], 0)
            warnings = query_mirror(run_id, "SELECT kind FROM projection_warnings", data_dir=data_dir)
            self.assertIn({"kind": "unknown_schema_version"}, warnings)

    def test_projector_uses_sqlite_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            run_id = materialize_fixture("clean-single-phase", data_dir)
            project_run(run_id, data_dir=data_dir)
            with closing(sqlite3.connect(mirror_path_for(run_id, data_dir=data_dir))) as conn:
                self.assertEqual(conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")


if __name__ == "__main__":
    unittest.main()
