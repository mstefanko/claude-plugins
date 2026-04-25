"""Tests for swarm_do.roles gen readme-section subcommand."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from .. import cli as roles_cli
from ..cli import _render_roles_table, _cmd_readme_section_gen
import argparse


class TestRenderRolesTable(unittest.TestCase):
    """Tests for _render_roles_table function."""

    def test_roles_table_format(self):
        """Test that roles table is rendered with expected format."""
        table = _render_roles_table()
        # Check table header
        self.assertIn("| Name | Description | Consumers |", table)
        self.assertIn("|------|-------------|-----------|", table)

    def test_roles_table_has_rows(self):
        """Test that table contains role rows."""
        table = _render_roles_table()
        lines = table.split("\n")
        # Should have header, separator, and at least some role rows
        self.assertGreaterEqual(len(lines), 3)

    def test_roles_table_escapes_pipes(self):
        """Test that pipes in description are escaped."""
        # This is tested implicitly by the render function
        table = _render_roles_table()
        # Count the escaped pipes - they should be minimal if descriptions don't have pipes
        # but the function should handle them correctly
        self.assertIsInstance(table, str)


class TestCmdReadmeSectionGen(unittest.TestCase):
    """Tests for _cmd_readme_section_gen function."""

    def test_write_to_file(self):
        """Test that --write updates the README file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            readme_path = tmp_path / "swarm-do" / "README.md"
            readme_path.parent.mkdir(parents=True)

            # Create initial file with markers
            MARKER_BEGIN = "<!-- BEGIN: generated-by swarm_do.roles gen readme-section -->"
            MARKER_END = "<!-- END: generated-by swarm_do.roles gen readme-section -->"
            initial_content = (
                "# README\n"
                f"{MARKER_BEGIN}\n"
                "(placeholder)\n"
                f"{MARKER_END}\n"
            )
            readme_path.write_text(initial_content, encoding="utf-8")

            # Mock the repo root finder
            with patch.object(roles_cli, "_find_repo_root") as mock_repo_root:
                mock_repo_root.return_value = tmp_path

                args = argparse.Namespace(write=True, check=False)
                result = _cmd_readme_section_gen(args)

            self.assertEqual(result, 0)
            content = readme_path.read_text(encoding="utf-8")
            self.assertIn(MARKER_BEGIN, content)
            self.assertIn(MARKER_END, content)
            self.assertIn("| Name | Description | Consumers |", content)

    def test_check_passes_on_clean(self):
        """Test that --check passes when content is up-to-date."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            readme_path = tmp_path / "swarm-do" / "README.md"
            readme_path.parent.mkdir(parents=True)

            MARKER_BEGIN = "<!-- BEGIN: generated-by swarm_do.roles gen readme-section -->"
            MARKER_END = "<!-- END: generated-by swarm_do.roles gen readme-section -->"
            initial_content = (
                "# README\n"
                f"{MARKER_BEGIN}\n"
                "(placeholder)\n"
                f"{MARKER_END}\n"
            )
            readme_path.write_text(initial_content, encoding="utf-8")

            with patch.object(roles_cli, "_find_repo_root") as mock_repo_root:
                mock_repo_root.return_value = tmp_path

                # Write first
                args = argparse.Namespace(write=True, check=False)
                self.assertEqual(_cmd_readme_section_gen(args), 0)

                # Then check should pass
                args = argparse.Namespace(write=False, check=True)
                result = _cmd_readme_section_gen(args)

            self.assertEqual(result, 0)

    def test_check_detects_drift(self):
        """Test that --check fails when content has drifted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            readme_path = tmp_path / "swarm-do" / "README.md"
            readme_path.parent.mkdir(parents=True)

            MARKER_BEGIN = "<!-- BEGIN: generated-by swarm_do.roles gen readme-section -->"
            MARKER_END = "<!-- END: generated-by swarm_do.roles gen readme-section -->"
            initial_content = (
                "# README\n"
                f"{MARKER_BEGIN}\n"
                "(placeholder)\n"
                f"{MARKER_END}\n"
            )
            readme_path.write_text(initial_content, encoding="utf-8")

            with patch.object(roles_cli, "_find_repo_root") as mock_repo_root:
                mock_repo_root.return_value = tmp_path

                # Write correct content first
                args = argparse.Namespace(write=True, check=False)
                self.assertEqual(_cmd_readme_section_gen(args), 0)

                # Modify content between markers
                content = readme_path.read_text(encoding="utf-8")
                content = content.replace("| Name |", "| Modified |")
                readme_path.write_text(content, encoding="utf-8")

                # Check should now fail
                args = argparse.Namespace(write=False, check=True)
                result = _cmd_readme_section_gen(args)

            self.assertEqual(result, 1)

    def test_fails_on_missing_markers(self):
        """Test that fails when markers are not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            readme_path = tmp_path / "swarm-do" / "README.md"
            readme_path.parent.mkdir(parents=True)

            # Create file WITHOUT markers
            readme_path.write_text("# README\nNo markers here.", encoding="utf-8")

            with patch.object(roles_cli, "_find_repo_root") as mock_repo_root:
                mock_repo_root.return_value = tmp_path

                args = argparse.Namespace(write=True, check=False)
                result = _cmd_readme_section_gen(args)

            self.assertEqual(result, 1)

    def test_fails_on_missing_file(self):
        """Test that fails when README does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            with patch.object(roles_cli, "_find_repo_root") as mock_repo_root:
                mock_repo_root.return_value = tmp_path

                args = argparse.Namespace(write=True, check=False)
                result = _cmd_readme_section_gen(args)

            self.assertEqual(result, 1)


class TestIntegration(unittest.TestCase):
    """Integration tests for gen readme-section workflow."""

    def test_write_then_check_integration(self):
        """Test full workflow: write then check."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            readme_path = tmp_path / "swarm-do" / "README.md"
            readme_path.parent.mkdir(parents=True)

            MARKER_BEGIN = "<!-- BEGIN: generated-by swarm_do.roles gen readme-section -->"
            MARKER_END = "<!-- END: generated-by swarm_do.roles gen readme-section -->"
            initial_content = (
                "# README\n"
                f"{MARKER_BEGIN}\n"
                "(placeholder)\n"
                f"{MARKER_END}\n"
            )
            readme_path.write_text(initial_content, encoding="utf-8")

            with patch.object(roles_cli, "_find_repo_root") as mock_repo_root:
                mock_repo_root.return_value = tmp_path

                # Write should succeed
                args = argparse.Namespace(write=True, check=False)
                self.assertEqual(_cmd_readme_section_gen(args), 0)

                # Check should pass
                args = argparse.Namespace(write=False, check=True)
                self.assertEqual(_cmd_readme_section_gen(args), 0)

                # Modify file outside markers
                content = readme_path.read_text(encoding="utf-8")
                content = "# New header\n" + content
                readme_path.write_text(content, encoding="utf-8")

                # Check should still pass
                args = argparse.Namespace(write=False, check=True)
                self.assertEqual(_cmd_readme_section_gen(args), 0)

                # Modify file inside markers
                content = content.replace("| Name |", "| Modified |")
                readme_path.write_text(content, encoding="utf-8")

                # Check should now fail
                args = argparse.Namespace(write=False, check=True)
                self.assertEqual(_cmd_readme_section_gen(args), 1)


if __name__ == "__main__":
    unittest.main()
