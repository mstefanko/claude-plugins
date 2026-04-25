from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.decompose import decompose_phase, decompose_plan_phase
from swarm_do.pipeline.plan import parse_plan
from swarm_do.pipeline.validation import schema_lint_work_units


class DecomposeLintTests(unittest.TestCase):
    def test_simple_phase_synthesizes_one_v2_unit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.md"
            path.write_text("### Phase 1: Docs\n- Update `README.md`.\n", encoding="utf-8")
            result = decompose_plan_phase(path, "1")
        self.assertFalse(result.lint.errors)
        self.assertEqual(result.artifact["schema_version"], 2)
        self.assertEqual(len(result.artifact["work_units"]), 1)
        self.assertEqual(result.artifact["work_units"][0]["allowed_files"], ["README.md"])

    def test_agent_lint_failure_retries_once_then_escalates(self) -> None:
        phase = parse_plan_text("### Phase 1: Hard (complexity: hard, kind: feature)\n- Work on `py/a.py`.\n")[0]
        calls = []

        def bad_runner(_phase, _report, lint_errors):
            calls.append(list(lint_errors))
            return {"schema_version": 2, "work_units": []}

        result = decompose_phase(phase, agent_runner=bad_runner)
        self.assertTrue(result.escalated)
        self.assertEqual(result.retry_count, 1)
        self.assertEqual(len(calls), 2)

    def test_lint_rejects_parallel_file_overlap(self) -> None:
        artifact = {
            "schema_version": 2,
            "work_units": [
                v2_unit("unit-a", ["py/a.py"], []),
                v2_unit("unit-b", ["py/a.py"], []),
            ],
        }
        lint = schema_lint_work_units(artifact)
        self.assertTrue(any("overlapping allowed_files" in error for error in lint.errors))


def parse_plan_text(text: str):
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "plan.md"
        path.write_text(text, encoding="utf-8")
        return parse_plan(path)


def v2_unit(unit_id: str, files: list[str], depends_on: list[str]) -> dict:
    return {
        "id": unit_id,
        "title": unit_id,
        "goal": "goal",
        "depends_on": depends_on,
        "context_files": [],
        "allowed_files": files,
        "blocked_files": [],
        "acceptance_criteria": ["passes"],
        "validation_commands": [],
        "expected_results": [],
        "risk_tags": [],
        "handoff_notes": "",
        "beads_id": None,
        "worktree_branch": None,
        "status": "pending",
        "failure_reason": None,
        "retry_count": 0,
        "handoff_count": 0,
    }


if __name__ == "__main__":
    unittest.main()
