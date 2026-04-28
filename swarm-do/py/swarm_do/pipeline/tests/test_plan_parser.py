from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.plan import parse_plan


class PlanParserTests(unittest.TestCase):
    def test_parse_phase_heading_tags_and_files(self) -> None:
        text = """# Plan

### Phase 1: Parser work (complexity: moderate, kind: feature)

Files affected
- py/swarm_do/pipeline/plan.py
- py/swarm_do/pipeline/cli.py

- Add parser.
- Add CLI.
"""
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.md"
            path.write_text(text, encoding="utf-8")
            phases = parse_plan(path)
        self.assertEqual(len(phases), 1)
        self.assertEqual(phases[0].phase_id, "1")
        self.assertEqual(phases[0].complexity, "moderate")
        self.assertEqual(phases[0].kind, "feature")
        self.assertIn("py/swarm_do/pipeline/plan.py", phases[0].explicit_files)
        self.assertGreaterEqual(phases[0].implementation_bullets, 2)

    def test_plan_without_phase_headings_becomes_single_inferred_phase(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "scratch.md"
            path.write_text("- Update `README.md`.\n", encoding="utf-8")
            phases = parse_plan(path)
        self.assertEqual(len(phases), 1)
        self.assertEqual(phases[0].phase_id, "plan")
        self.assertEqual(phases[0].referenced_files, ["README.md"])



class StripTagsTests(unittest.TestCase):
    """Bug 3: _strip_tags must strip em-dash + bold markers."""

    def test_em_dash_and_bold_complexity_tag(self) -> None:
        from swarm_do.pipeline.plan import _strip_tags

        title = "— Prepared Run Artifact Contract  *(complexity: moderate, kind: foundation)*"
        self.assertEqual(_strip_tags(title), "Prepared Run Artifact Contract")

    def test_en_dash_prefix(self) -> None:
        from swarm_do.pipeline.plan import _strip_tags

        self.assertEqual(_strip_tags("– Foo"), "Foo")

    def test_no_tag_no_strip(self) -> None:
        from swarm_do.pipeline.plan import _strip_tags

        self.assertEqual(_strip_tags("Plain Title"), "Plain Title")


class LooksLikePathTests(unittest.TestCase):
    """Bug 4: _looks_like_path must reject slash-joined non-path tokens."""

    def test_stoplist_rejected(self) -> None:
        from swarm_do.pipeline.plan import _looks_like_path

        for token in ("accept/reject", "read/write", "inspect/decompose", "and/or", "yes/no"):
            self.assertFalse(_looks_like_path(token), token)

    def test_known_top_level_dirs_accepted(self) -> None:
        from swarm_do.pipeline.plan import _looks_like_path

        for token in (
            "py/swarm_do/pipeline/plan.py",
            "swarm-do/bin/swarm",
            "docs/swarmdaddy-prepare-gate-plan.md",
            "schemas/work_units.schema.json",
        ):
            self.assertTrue(_looks_like_path(token), token)

    def test_extension_only_accepted(self) -> None:
        from swarm_do.pipeline.plan import _looks_like_path

        self.assertTrue(_looks_like_path("README.md"))
        self.assertTrue(_looks_like_path("foo/bar/baz.py"))


class ExtractReferencedFilesTests(unittest.TestCase):
    """Bug 5: _extract_referenced_files must NOT pull paths from code fences."""

    def test_fence_content_excluded(self) -> None:
        from swarm_do.pipeline.plan import _extract_referenced_files

        text = (
            "Here is `py/other/file.py` inline.\n\n"
            "```\nrg -n 'pattern' py/some/file.py\n```\n"
        )
        result = _extract_referenced_files(text)
        self.assertEqual(result, ["py/other/file.py"])


class ExtractExplicitFilesTests(unittest.TestCase):
    """AC10: _extract_explicit_files reads until next markdown heading, not 80 lines."""

    def test_long_file_targets_table(self) -> None:
        from swarm_do.pipeline.plan import _extract_explicit_files

        rows = [f"- `py/swarm_do/m{i:03d}.py`" for i in range(100)]
        lines = ["### File Targets", ""] + rows + ["", "### Other section"]
        result = _extract_explicit_files(lines)
        self.assertEqual(len(result), 100)
        self.assertIn("py/swarm_do/m099.py", result)


class InspectPhaseNoFallbackTests(unittest.TestCase):
    """AC6: inspect_phase.file_paths does not fall through to referenced_files."""

    def test_phase_without_file_targets_yields_empty_file_paths(self) -> None:
        import tempfile

        from swarm_do.pipeline.plan import inspect_plan

        text = (
            "### Phase 1: Narrative\n\n"
            "We touch `py/foo/bar.py` and `py/baz/qux.py` inline.\n"
            "- Update.\n"
        )
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "plan.md"
            path.write_text(text, encoding="utf-8")
            reports = inspect_plan(path)
        self.assertEqual(reports[0].file_paths, [])

if __name__ == "__main__":
    unittest.main()
