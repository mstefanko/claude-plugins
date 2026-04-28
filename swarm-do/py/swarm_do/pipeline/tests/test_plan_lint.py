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


if __name__ == "__main__":
    unittest.main()
