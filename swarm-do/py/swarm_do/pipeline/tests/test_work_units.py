from __future__ import annotations

import unittest

from swarm_do.pipeline.work_units import retry_state_transition, topological_work_unit_layers


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


if __name__ == "__main__":
    unittest.main()
