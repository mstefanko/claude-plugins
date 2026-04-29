from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline import context_bundle
from swarm_do.pipeline.context_bundle import render_context_bundle
from swarm_do.pipeline.phase_sessions import init_phase_sessions, phase_session_path
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

    def test_context_schema_errors_raise_value_error(self) -> None:
        with self.assertRaises(ValueError) as caught:
            context_bundle._validate_context({"schema_version": 1})

        self.assertIs(type(caught.exception), ValueError)

    def test_phase_three_uses_direct_dependency_handoff_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=3)
            _write_handoff(data, run_id, "1", summary="phase one summary", decisions=["phase one decision"])
            _write_handoff(data, run_id, "2", summary="phase two summary", decisions=["phase two decision"])

            result = render_context_bundle(run_id=run_id, phase_id="3", role="dispatcher", data_dir=data, repo_root=repo)

            context_dir = data / "runs" / run_id / "context" / "3"
            previous = (context_dir / "previous-handoff.md").read_text(encoding="utf-8")
            decisions = (context_dir / "decisions.md").read_text(encoding="utf-8")
            shared = (context_dir / "shared-decisions.md").read_text(encoding="utf-8")
            self.assertNotIn("phase one summary", previous)
            self.assertIn("phase two summary", previous)
            self.assertNotIn("phase one decision", decisions)
            self.assertIn("phase two decision", decisions)
            self.assertEqual(shared, "No shared decisions.\n")
            self.assertIn("shared_decisions_path", result["context"])

    def test_phase_session_dependencies_override_prepared_fallback_for_handoffs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=3)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            state_path = phase_session_path(run_id, data_dir=data)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["phases"][2]["depends_on_phase_ids"] = ["1"]
            state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            _write_handoff(data, run_id, "1", summary="phase one summary")
            _write_handoff(data, run_id, "2", summary="phase two summary")

            render_context_bundle(run_id=run_id, phase_id="3", role="dispatcher", data_dir=data, repo_root=repo)

            previous = (data / "runs" / run_id / "context" / "3" / "previous-handoff.md").read_text(encoding="utf-8")
            self.assertIn("phase one summary", previous)
            self.assertNotIn("phase two summary", previous)

    def test_explicit_empty_prepared_dependencies_do_not_fall_back(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=3)
            prepared_path = data / "runs" / run_id / "prepared_plan.v1.json"
            prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
            prepared["phase_map"][2]["depends_on_phase_ids"] = []
            prepared_path.write_text(json.dumps(prepared, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            _write_handoff(data, run_id, "2", summary="phase two summary")

            render_context_bundle(run_id=run_id, phase_id="3", role="dispatcher", data_dir=data, repo_root=repo)

            previous = (data / "runs" / run_id / "context" / "3" / "previous-handoff.md").read_text(encoding="utf-8")
            self.assertEqual(previous, "No previous phase handoff.\n")

    def test_dependency_handoff_uses_highest_numeric_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=2)
            _write_handoff(data, run_id, "1", attempt=2, summary="attempt two summary")
            _write_handoff(data, run_id, "1", attempt=10, summary="attempt ten summary")

            render_context_bundle(run_id=run_id, phase_id="2", role="dispatcher", data_dir=data, repo_root=repo)

            previous = (data / "runs" / run_id / "context" / "2" / "previous-handoff.md").read_text(encoding="utf-8")
            self.assertIn("attempt ten summary", previous)
            self.assertNotIn("attempt two summary", previous)

    def test_retry_dispatcher_prompt_includes_recovery_context(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo, data, run_id = make_prepared_run(Path(td), phase_count=1)
            init_phase_sessions(run_id, data_dir=data, repo_root=repo)
            recovery_path = data / "runs" / run_id / "phase_recovery" / "1" / "attempt-1.recovery.md"
            recovery_path.parent.mkdir(parents=True, exist_ok=True)
            recovery_path.write_text(
                "# Recovery Context\n- launch_dir: data/runs/x/phase_launches/1/attempt-1\n- changed_files: docs/x.md\n",
                encoding="utf-8",
            )
            state_path = phase_session_path(run_id, data_dir=data)
            state = json.loads(state_path.read_text(encoding="utf-8"))
            phase = state["phases"][0]
            phase["attempt"] = 1
            phase["status"] = "pending"
            phase["attempt_history"] = [
                {
                    "attempt": 1,
                    "failure_kind": "timeout",
                    "retry_decision": "recovery_retry",
                    "adopted": False,
                    "recovery_context_path": str(recovery_path),
                }
            ]
            state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = render_context_bundle(run_id=run_id, phase_id="1", role="dispatcher", data_dir=data, repo_root=repo)

            prompt = Path(result["prompt_path"]).read_text(encoding="utf-8")
            self.assertIn("## Recovery Context", prompt)
            self.assertIn("attempt-1.recovery.md", prompt)
            self.assertEqual(result["context"]["recovery_context_path"], str(recovery_path))


def _write_handoff(
    data: Path,
    run_id: str,
    phase_id: str,
    *,
    attempt: int = 1,
    summary: str,
    decisions: list[str] | None = None,
) -> None:
    path = data / "runs" / run_id / "phase_handoffs" / phase_id / f"attempt-{attempt}.handoff.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "run_id": run_id,
        "phase_id": phase_id,
        "phase_attempt": attempt,
        "status": "complete",
        "written_at": "2026-04-29T00:00:00Z",
        "summary": summary,
        "decisions": decisions or [],
        "changed_files": [],
        "completed_work_units": [],
        "open_items": [],
        "blockers": [],
        "do_not_retry": [],
        "validation_summary": [],
        "artifacts": [],
        "next_phase_context": [f"{phase_id} next context"],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
