from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.executor import (
    beads_update_allowed,
    execution_batches,
    load_work_units,
    next_resume_point,
    ready_work_units,
)


def three_unit_artifact() -> dict:
    return {
        "schema_version": 1,
        "plan_path": None,
        "bd_epic_id": "bd-epic",
        "work_units": [
            unit("unit-a", []),
            unit("unit-b", ["unit-a"]),
            unit("unit-c", ["unit-a"]),
        ],
    }


def unit(unit_id: str, depends_on: list[str]) -> dict:
    return {
        "id": unit_id,
        "depends_on": depends_on,
        "files": [f"{unit_id}.txt"],
        "acceptance_criteria": [f"{unit_id} passes"],
        "beads_id": None,
        "worktree_branch": None,
        "status": "pending",
        "retry_count": 0,
        "handoff_count": 0,
    }


class ExecutorTests(unittest.TestCase):
    def test_parallel_wave_splits_by_parallelism(self) -> None:
        artifact = three_unit_artifact()
        state = {"unit-a": "merged"}

        self.assertEqual(ready_work_units(artifact, state), ["unit-b", "unit-c"])
        self.assertEqual(execution_batches(artifact, state, parallelism=2), [["unit-b", "unit-c"]])

    def test_serial_fallback_produces_stable_singleton_batches(self) -> None:
        artifact = three_unit_artifact()
        state = {"unit-a": {"status": "approved"}}

        self.assertEqual(execution_batches(artifact, state, parallelism=1), [["unit-b"], ["unit-c"]])
        self.assertEqual(execution_batches(artifact, state, parallelism=0), [["unit-b"], ["unit-c"]])

    def test_load_rejects_missing_dependency(self) -> None:
        artifact = three_unit_artifact()
        artifact["work_units"][1]["depends_on"] = ["missing"]

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "work-units.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "unknown work unit missing"):
                load_work_units(path)

    def test_load_rejects_cycle(self) -> None:
        artifact = {
            "schema_version": 1,
            "work_units": [
                unit("unit-a", ["unit-b"]),
                unit("unit-b", ["unit-a"]),
            ],
        }

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "work-units.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cycle detected"):
                load_work_units(path)

    def test_resume_point_after_partially_merged_units(self) -> None:
        artifact = three_unit_artifact()
        state = {"unit-a": "merged", "unit-b": "failed", "unit-c": "pending"}

        self.assertEqual(next_resume_point(artifact, state), {"work_unit_id": "unit-b", "status": "failed"})

    def test_coordinator_only_beads_update_discipline(self) -> None:
        self.assertTrue(beads_update_allowed("coordinator", "merge_state"))
        self.assertTrue(beads_update_allowed("agent-writer", "child_note", owns_child_issue=True))
        self.assertFalse(beads_update_allowed("agent-writer", "run_event", owns_child_issue=True))
        self.assertFalse(beads_update_allowed("agent-writer", "child_note", owns_child_issue=False))


if __name__ == "__main__":
    unittest.main()
