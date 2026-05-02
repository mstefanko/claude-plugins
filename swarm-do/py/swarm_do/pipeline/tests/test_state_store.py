from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from swarm_do.pipeline import phase_session_store, state_store, worktree_state_store
from swarm_do.pipeline.prepared_artifact_writer import (
    RunStateStore as PreparedArtifactRunStateStore,
)
from swarm_do.pipeline.prepared_artifact_writer import (
    RunStateTxn as PreparedArtifactRunStateTxn,
)
from swarm_do.pipeline.run_state import JsonRunEventSink


PIPELINE_ROOT = Path(__file__).resolve().parents[1]


class StateStoreProtocolTests(unittest.TestCase):
    def test_prepared_artifact_writer_reexports_moved_protocols(self) -> None:
        self.assertIs(PreparedArtifactRunStateStore, state_store.RunStateStore)
        self.assertIs(PreparedArtifactRunStateTxn, state_store.RunStateTxn)

    def test_state_store_imports_no_owner_modules(self) -> None:
        tree = ast.parse((PIPELINE_ROOT / "state_store.py").read_text(encoding="utf-8"))
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)

        banned = {
            "execution_worktree",
            "phase_decisions",
            "phase_evidence",
            "phase_sessions",
            "prepared_artifact_writer",
            "run_state",
            "stage_sessions",
        }
        self.assertTrue(imports.isdisjoint(banned), imports & banned)

    def test_protocols_stay_small(self) -> None:
        tree = ast.parse((PIPELINE_ROOT / "state_store.py").read_text(encoding="utf-8"))
        method_counts: dict[str, int] = {}
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                method_counts[node.name] = sum(
                    isinstance(child, ast.FunctionDef) for child in node.body
                )

        for name in (
            "RunStateTxn",
            "RunStateStore",
            "PreparedArtifactStore",
            "PhaseSessionStore",
            "WorktreeStateStore",
            "RunEventSink",
        ):
            self.assertLessEqual(method_counts[name], 6, name)


class StateStoreWrapperTests(unittest.TestCase):
    def test_phase_session_store_paths_match_owner_module(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            store = phase_session_store.JsonPhaseSessionStore(data_dir=data)

            self.assertEqual(
                store.state_path("run-1"),
                phase_session_store.phase_session_path("run-1", data_dir=data),
            )
            self.assertEqual(
                store.result_path("run-1", "phase-1", 2),
                phase_session_store.phase_result_path("run-1", "phase-1", 2, data_dir=data),
            )
            self.assertEqual(
                store.handoff_path("run-1", "phase-1", 2),
                phase_session_store.phase_handoff_path("run-1", "phase-1", 2, data_dir=data),
            )

    def test_phase_session_store_delegates_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            repo = data / "repo"
            store = phase_session_store.JsonPhaseSessionStore(data_dir=data, repo_root=repo)
            with mock.patch.object(
                phase_session_store._phase_sessions,
                "init_phase_sessions",
                return_value={"initialized": True},
            ) as init:
                self.assertEqual(store.init("run-1", mode="test"), {"initialized": True})
                init.assert_called_once_with(
                    "run-1",
                    data_dir=data,
                    repo_root=repo,
                    mode="test",
                    policy_update=None,
                )

            result_path = data / "result.json"
            with mock.patch.object(
                phase_session_store._phase_sessions,
                "record_phase_result",
                return_value={"recorded": True},
            ) as record:
                self.assertEqual(
                    store.record_result("run-1", "phase-1", json_file=result_path),
                    {"recorded": True},
                )
                record.assert_called_once_with(
                    "run-1",
                    "phase-1",
                    json_file=result_path,
                    expected_status=None,
                    data_dir=data,
                )

    def test_worktree_state_store_delegates_mutations(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            store = worktree_state_store.JsonWorktreeStateStore(data_dir=data)
            with mock.patch.object(
                worktree_state_store._execution_worktree,
                "adopt_run_worktree",
                return_value={"adopted": True},
            ) as adopt:
                self.assertEqual(store.adopt("run-1", apply=True), {"adopted": True})
                adopt.assert_called_once_with("run-1", data_dir=data, apply=True)

            with mock.patch.object(
                worktree_state_store._execution_worktree,
                "integrate_run_worktree",
                return_value={"integrated": True},
            ) as integrate:
                self.assertEqual(store.integrate("run-1"), {"integrated": True})
                integrate.assert_called_once_with("run-1", data_dir=data, apply=False)

    def test_run_event_sink_appends_jsonl_through_owner(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            data = Path(td)
            path = JsonRunEventSink(data_dir=data).append(
                {"run_id": "run-1", "event_type": "unit-test", "details": {}}
            )

            self.assertEqual(path, data / "telemetry" / "run_events.jsonl")
            row = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(row["run_id"], "run-1")
            self.assertEqual(row["schema_ok"], True)
            self.assertIn("timestamp", row)


if __name__ == "__main__":
    unittest.main()
