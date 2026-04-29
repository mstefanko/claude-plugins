"""Tests for ``plan.lint_plan_text`` heading and section detection.

These guards cover two flavors of plan markdown that regularly land in
``swarm-do/docs/``:

* **Conventional**: ``## Phase 1 - …`` with ``### Acceptance`` and a
  project-wide ``## Test Strategy`` block.
* **Canonical**: ``### Phase 1: …`` with ``### Acceptance Criteria`` and
  ``### Verification Commands`` per phase (what ``canonical_plan_text``
  emits and what older test fixtures use).

Both must lint without a ``no_phase_headings`` /
``missing_acceptance_criteria`` / ``missing_validation_commands`` blocker.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from swarm_do.pipeline.plan import lint_plan_text


def _codes(findings: list[dict[str, object]]) -> set[str]:
    return {str(f["code"]) for f in findings}


class PhaseHeadingDetectionTests(unittest.TestCase):
    def test_h2_phase_heading_is_detected(self) -> None:
        text = (
            "## Phase 1 - Foo\n\n"
            "### Acceptance\n- ok\n\n"
            "### Verification Commands\n```bash\ntrue\n```\n"
        )
        codes = _codes(lint_plan_text(text, source_name="<test>"))
        self.assertNotIn("no_phase_headings", codes)
        self.assertNotIn("missing_acceptance_criteria", codes)
        self.assertNotIn("missing_validation_commands", codes)

    def test_h3_phase_heading_still_works(self) -> None:
        text = (
            "### Phase 1: Foo\n\n"
            "### Acceptance Criteria\n- ok\n\n"
            "### Verification Commands\n```bash\ntrue\n```\n"
        )
        codes = _codes(lint_plan_text(text, source_name="<test>"))
        self.assertNotIn("no_phase_headings", codes)
        self.assertNotIn("missing_acceptance_criteria", codes)
        self.assertNotIn("missing_validation_commands", codes)

    def test_h4_phase_heading_is_not_detected(self) -> None:
        # Plans should not be allowed to bury phases at h4 — keep the
        # detector tight enough to prevent that.
        text = "#### Phase 1: Foo\n- bullet\n"
        codes = _codes(lint_plan_text(text, source_name="<test>"))
        self.assertIn("no_phase_headings", codes)


class AcceptanceSectionTests(unittest.TestCase):
    def test_acceptance_without_criteria_word_is_recognized(self) -> None:
        text = (
            "## Phase 1 - Foo\n\n"
            "### Acceptance\n- ok\n\n"
            "### Verification Commands\n```bash\ntrue\n```\n"
        )
        codes = _codes(lint_plan_text(text, source_name="<test>"))
        self.assertNotIn("missing_acceptance_criteria", codes)

    def test_acceptance_criteria_phrasing_still_recognized(self) -> None:
        text = (
            "### Phase 1: Foo\n\n"
            "### Acceptance Criteria\n- ok\n\n"
            "### Verification Commands\n```bash\ntrue\n```\n"
        )
        codes = _codes(lint_plan_text(text, source_name="<test>"))
        self.assertNotIn("missing_acceptance_criteria", codes)


class PlanLevelTestStrategyFallbackTests(unittest.TestCase):
    def test_test_strategy_block_downgrades_missing_validation(self) -> None:
        text = (
            "## Phase 1 - Foo\n\n"
            "### Acceptance\n- ok\n\n"
            "## Test Strategy\n```bash\ntrue\n```\n"
        )
        codes = _codes(lint_plan_text(text, source_name="<test>"))
        self.assertNotIn("missing_validation_commands", codes)
        self.assertIn("validation_commands_from_plan_level", codes)

    def test_definition_of_done_also_qualifies(self) -> None:
        text = (
            "## Phase 1 - Foo\n\n"
            "### Acceptance\n- ok\n\n"
            "## Definition Of Done\n- run unit tests\n"
        )
        codes = _codes(lint_plan_text(text, source_name="<test>"))
        self.assertNotIn("missing_validation_commands", codes)
        self.assertIn("validation_commands_from_plan_level", codes)

    def test_no_fallback_block_keeps_blocking_severity(self) -> None:
        text = (
            "## Phase 1 - Foo\n\n"
            "### Acceptance\n- ok\n"
        )
        codes = _codes(lint_plan_text(text, source_name="<test>"))
        self.assertIn("missing_validation_commands", codes)
        self.assertNotIn("validation_commands_from_plan_level", codes)

    def test_per_phase_validation_overrides_plan_level_fallback(self) -> None:
        text = (
            "## Phase 1 - Foo\n\n"
            "### Acceptance\n- ok\n\n"
            "### Verification Commands\n```bash\ntrue\n```\n\n"
            "## Test Strategy\n```bash\nfalse\n```\n"
        )
        codes = _codes(lint_plan_text(text, source_name="<test>"))
        self.assertNotIn("missing_validation_commands", codes)
        self.assertNotIn("validation_commands_from_plan_level", codes)


class BuildOrderLintTests(unittest.TestCase):
    def test_validation_referencing_later_phase_file_is_blocking(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "build_order" / "reversed_dependency_plan.md"
        findings = lint_plan_text(fixture.read_text(encoding="utf-8"), source_name=str(fixture))
        by_code = {str(item["code"]): item for item in findings}

        self.assertIn("validation_uses_later_phase_file", by_code)
        self.assertEqual(by_code["validation_uses_later_phase_file"]["severity"], "blocking")

    def test_valid_sequential_build_order_is_clean(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "build_order" / "valid_sequential_plan.md"
        codes = _codes(lint_plan_text(fixture.read_text(encoding="utf-8"), source_name=str(fixture)))

        self.assertNotIn("validation_uses_later_phase_file", codes)
        self.assertNotIn("overlapping_file_scope_without_order_note", codes)
        self.assertNotIn("phase_order_ambiguous_validation", codes)

    def test_adjacent_overlap_without_order_note_is_advisory(self) -> None:
        text = (
            "### Phase 1: First\n\n"
            "### File Targets\n- `py/shared.py`\n\n"
            "### Acceptance Criteria\n- ok\n\n"
            "### Validation Commands\n```\ntrue\n```\n\n"
            "### Phase 2: Second\n\n"
            "### File Targets\n- `py/shared.py`\n\n"
            "### Acceptance Criteria\n- ok\n\n"
            "### Validation Commands\n```\ntrue\n```\n"
        )
        findings = lint_plan_text(text, source_name="<test>")
        overlap = [item for item in findings if item["code"] == "overlapping_file_scope_without_order_note"]

        self.assertEqual(len(overlap), 1)
        self.assertEqual(overlap[0]["severity"], "advisory")


if __name__ == "__main__":
    unittest.main()
