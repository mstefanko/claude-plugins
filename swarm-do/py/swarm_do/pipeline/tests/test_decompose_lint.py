from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.decompose import decompose_phase, decompose_plan_phase
from swarm_do.pipeline.plan import parse_plan
from swarm_do.pipeline.validation import schema_lint_work_units


class DecomposeLintTests(unittest.TestCase):
    def test_simple_phase_synthesizes_one_v2_unit(self) -> None:
        # Explicit Files-affected section required after AC6: inspect_phase
        # no longer falls through to referenced_files for file_paths.
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.md"
            path.write_text(
                "### Phase 1: Docs\n\nFiles affected\n- README.md\n\n- Update `README.md`.\n",
                encoding="utf-8",
            )
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

    def test_semantic_clusters_do_not_chain_independent_units(self) -> None:
        phase = parse_plan_text(
            "### Phase 4: Prepare (complexity: moderate, kind: feature)\n\n"
            "### File Targets\n\n"
            "| Path | Action |\n"
            "| --- | --- |\n"
            "| `py/swarm_do/pipeline/plan.py` | EXTEND parser |\n"
            "| `py/swarm_do/pipeline/cli.py` | EXTEND CLI |\n"
            "| `docs/testing-strategy.md` | EXTEND docs |\n\n"
            "### Acceptance Criteria\n\n"
            "- Parser emits stable findings.\n"
            "- CLI validates prepare runs.\n"
            "- Docs describe the smoke command.\n\n"
            "### Verification Commands\n\n"
            "```\npython3 -m unittest discover -s py/swarm_do/pipeline/tests -p 'test_decompose*.py'\n```\n"
        )[0]
        result = decompose_phase(phase)

        self.assertFalse(result.lint.errors)
        units = result.artifact["work_units"]
        parser_unit = next(unit for unit in units if "py/swarm_do/pipeline/plan.py" in unit["allowed_files"])
        cli_unit = next(unit for unit in units if "py/swarm_do/pipeline/cli.py" in unit["allowed_files"])
        docs_unit = next(unit for unit in units if "docs/testing-strategy.md" in unit["allowed_files"])
        self.assertIn(parser_unit["id"], cli_unit["depends_on"])
        self.assertEqual(docs_unit["depends_on"], [])

    def test_acceptance_heavy_single_file_splits_with_real_file_dependency(self) -> None:
        phase = parse_plan_text(
            "### Phase 9: Parser (complexity: moderate, kind: feature)\n\n"
            "### File Targets\n\n"
            "- `py/swarm_do/pipeline/plan.py`\n\n"
            "### Acceptance Criteria\n\n"
            "- AC1 plan parser.\n- AC2 plan parser.\n- AC3 plan parser.\n"
            "- AC4 plan parser.\n- AC5 plan parser.\n- AC6 plan parser.\n\n"
            "### Verification Commands\n\n```\npython3 -m unittest py.swarm_do.pipeline.tests.test_plan_parser\n```\n"
        )[0]
        result = decompose_phase(phase)

        self.assertFalse(result.lint.errors)
        units = result.artifact["work_units"]
        self.assertGreater(len(units), 1)
        self.assertEqual(units[1]["depends_on"], [units[0]["id"]])
        self.assertLessEqual(max(len(unit["acceptance_criteria"]) for unit in units), 5)


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



class AcceptanceCriteriaParserTests(unittest.TestCase):
    """Bug 1: _acceptance_criteria recognizes ### / **/ #### Acceptance headings."""

    def test_h3_acceptance_criteria_collected(self) -> None:
        from swarm_do.pipeline.decompose import _acceptance_criteria

        phase = parse_plan_text(
            "### Phase 1: Foo (complexity: moderate, kind: feature)\n\n"
            "### Acceptance criteria\n\n"
            "- AC1 the first.\n"
            "- AC2 the second.\n"
            "- AC3 the third.\n"
            "- AC4 the fourth.\n"
            "- AC5 the fifth.\n"
            "- AC6 the sixth.\n"
            "- AC7 the seventh.\n\n"
            "### Next section\n\n"
            "- not an AC.\n"
        )[0]
        result = _acceptance_criteria(phase)
        self.assertEqual(len(result), 7)
        self.assertEqual(result[0], "AC1 the first.")

    def test_bold_acceptance_criteria_collected(self) -> None:
        from swarm_do.pipeline.decompose import _acceptance_criteria

        phase = parse_plan_text(
            "### Phase 1: Foo\n\n"
            "**Acceptance Criteria:**\n\n"
            "- AC1.\n"
            "- AC2.\n"
        )[0]
        result = _acceptance_criteria(phase)
        self.assertEqual(result, ["AC1.", "AC2."])

    def test_no_section_returns_fallback(self) -> None:
        from swarm_do.pipeline.decompose import _acceptance_criteria

        phase = parse_plan_text("### Phase 1: Bare\n\n- Just a bullet.\n")[0]
        result = _acceptance_criteria(phase)
        self.assertEqual(len(result), 1)
        self.assertIn("Phase 1 objective", result[0])


class ValidationCommandsParserTests(unittest.TestCase):
    """Bug 2: _validation_commands matches Verification|Validation headings + captures fence content."""

    def test_h3_verification_commands_with_fence(self) -> None:
        from swarm_do.pipeline.decompose import _validation_commands

        phase = parse_plan_text(
            "### Phase 1: Foo\n\n"
            "### Verification commands\n\n"
            "```\n"
            "cd swarm-do && python3 -m unittest discover\n"
            "rg -n 'pattern' py/some/file.py\n"
            "```\n\n"
            "### Expected results\n\n"
            "- All green.\n"
        )[0]
        result = _validation_commands(phase)
        self.assertEqual(
            result,
            [
                "cd swarm-do && python3 -m unittest discover",
                "rg -n 'pattern' py/some/file.py",
            ],
        )

    def test_h3_validation_commands_alias(self) -> None:
        from swarm_do.pipeline.decompose import _validation_commands

        phase = parse_plan_text(
            "### Phase 1: Foo\n\n"
            "### Validation Commands\n\n"
            "```\n"
            "echo hello\n"
            "```\n"
        )[0]
        self.assertEqual(_validation_commands(phase), ["echo hello"])

    def test_no_section_returns_empty(self) -> None:
        from swarm_do.pipeline.decompose import _validation_commands

        phase = parse_plan_text("### Phase 1: Bare\n\n- A bullet.\n")[0]
        self.assertEqual(_validation_commands(phase), [])

if __name__ == "__main__":
    unittest.main()
