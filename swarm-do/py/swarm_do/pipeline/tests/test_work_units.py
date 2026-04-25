from __future__ import annotations

import unittest

from swarm_do.pipeline.validation import schema_lint_work_units
from swarm_do.pipeline.work_units import retry_state_transition, topological_work_unit_layers, unit_file_scope


class WorkUnitTests(unittest.TestCase):
    def test_topological_work_unit_layers(self) -> None:
        artifact = {
            "work_units": [
                {"id": "a", "depends_on": []},
                {"id": "b", "depends_on": ["a"]},
                {"id": "c", "depends_on": ["a"]},
            ]
        }
        self.assertEqual(topological_work_unit_layers(artifact), [["a"], ["b", "c"]])

    def test_cycle_detection(self) -> None:
        artifact = {"work_units": [{"id": "a", "depends_on": ["b"]}, {"id": "b", "depends_on": ["a"]}]}
        with self.assertRaisesRegex(ValueError, "cycle detected"):
            topological_work_unit_layers(artifact)

    def test_missing_dependency_detection(self) -> None:
        artifact = {"work_units": [{"id": "a", "depends_on": ["missing"]}]}
        with self.assertRaisesRegex(ValueError, "unknown id: missing"):
            topological_work_unit_layers(artifact)

    def test_retry_state_machine(self) -> None:
        self.assertEqual(retry_state_transition("APPROVED", 0), "approved")
        self.assertEqual(retry_state_transition("SPEC_MISMATCH", 1), "retry")
        self.assertEqual(retry_state_transition("SPEC_MISMATCH", 2), "escalate")
        self.assertEqual(retry_state_transition("NEEDS_CONTEXT", 0), "operator")

    def test_unit_file_scope_accepts_v1_and_v2_names(self) -> None:
        self.assertEqual(unit_file_scope({"files": ["a.py"]}), ["a.py"])
        self.assertEqual(unit_file_scope({"allowed_files": ["b.py"]}), ["b.py"])

    def test_v1_lint_returns_warning_shape(self) -> None:
        lint = schema_lint_work_units(
            {
                "schema_version": 1,
                "work_units": [
                    {
                        "id": "unit-a",
                        "depends_on": [],
                        "files": ["a.py"],
                        "acceptance_criteria": ["passes"],
                        "beads_id": None,
                        "worktree_branch": None,
                        "status": "pending",
                        "retry_count": 0,
                        "handoff_count": 0,
                    }
                ],
            }
        )
        self.assertFalse(lint.errors)
        self.assertTrue(lint.warnings)

    def test_v2_accepts_legacy_files_alias_with_warning(self) -> None:
        lint = schema_lint_work_units(
            {
                "schema_version": 2,
                "work_units": [
                    {
                        "id": "unit-a",
                        "title": "Unit A",
                        "goal": "Goal",
                        "depends_on": [],
                        "context_files": [],
                        "files": ["a.py"],
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
                ],
            }
        )
        self.assertFalse(lint.errors)
        self.assertTrue(lint.warnings)


if __name__ == "__main__":
    unittest.main()
