from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.cli import cmd_work_units
from swarm_do.pipeline.post_writer import build_post_writer_report


class PostWriterReportTests(unittest.TestCase):
    def test_report_includes_changed_files_diff_stat_validation_and_budget(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = init_repo(Path(td))
            write(repo / "py" / "a.py", "old\nnew\n")
            write(repo / "docs" / "new.md", "new doc\n")

            report = build_post_writer_report(
                artifact([unit("unit-a", ["py/a.py", "docs/new.md"], validation_commands=['python3 -c "print(\\"ok\\")"'])]),
                "unit-a",
                repo=repo,
                base_ref="HEAD",
                writer_return=writer_return("unit-a", tool_calls=3),
            )

        self.assertEqual(report["schema_version"], "post_writer_report.v1")
        self.assertEqual(report["unit_contract"]["allowed_files"], ["py/a.py", "docs/new.md"])
        self.assertEqual(report["acceptance_matrix"][0]["criterion"], "passes")
        self.assertEqual(report["acceptance_matrix"][0]["validation_status"], "passed")
        self.assertEqual(report["changed_files"], ["docs/new.md", "py/a.py"])
        self.assertEqual(report["diff_stat"]["files_changed"], 2)
        self.assertEqual(report["diff_stat"]["insertions"], 2)
        self.assertEqual(report["diff_stat"]["untracked_files"], ["docs/new.md"])
        self.assertEqual(report["test_summary"]["status"], "passed")
        self.assertEqual(report["test_summary"]["passed"], 1)
        self.assertEqual(report["budget_status"]["status"], "ok")
        self.assertEqual(report["gate"]["status"], "passed")

    def test_blocked_file_and_failed_validation_fail_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = init_repo(Path(td))
            write(repo / "secrets" / "token.txt", "secret\n")

            report = build_post_writer_report(
                artifact(
                    [
                        unit(
                            "unit-a",
                            ["py/a.py"],
                            blocked_files=["secrets/**"],
                            validation_commands=['python3 -c "import sys; print(\\"bad\\"); sys.exit(2)"'],
                        )
                    ]
                ),
                "unit-a",
                repo=repo,
                base_ref="HEAD",
                writer_return=writer_return("unit-a", tool_calls=3),
            )

        self.assertEqual(report["blocked_file_violations"], ["secrets/token.txt"])
        self.assertEqual(report["test_summary"]["status"], "failed")
        self.assertEqual(report["gate"]["status"], "failed")
        self.assertIn("blocked_file_violation", report["gate"]["failure_reasons"])
        self.assertIn("validation_failed", report["gate"]["failure_reasons"])

    def test_budget_breach_fails_gate(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = init_repo(Path(td))
            report = build_post_writer_report(
                artifact([unit("unit-a", ["py/a.py"])]),
                "unit-a",
                repo=repo,
                base_ref="HEAD",
                writer_return=writer_return("unit-a", tool_calls=99),
                max_writer_tool_calls=5,
            )

        self.assertEqual(report["budget_status"]["failure_reason"], "budget_breach_tool_calls")
        self.assertEqual(report["gate"]["status"], "failed")
        self.assertIn("budget_breach_tool_calls", report["gate"]["failure_reasons"])

    def test_cli_post_writer_emits_json_and_returns_gate_status(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = init_repo(root / "repo")
            write(repo / "py" / "a.py", "old\nnew\n")
            artifact_path = root / "work-units.json"
            artifact_path.write_text(
                json.dumps(artifact([unit("unit-a", ["py/a.py"], validation_commands=['python3 -c "print(\\"ok\\")"'])])),
                encoding="utf-8",
            )
            writer_path = root / "writer.txt"
            writer_path.write_text(writer_return("unit-a", tool_calls=2), encoding="utf-8")
            args = argparse.Namespace(
                work_units_command="post-writer",
                artifact=str(artifact_path),
                unit_id="unit-a",
                repo=str(repo),
                base_ref="HEAD",
                writer_return_file=str(writer_path),
                writer_return=None,
                max_writer_tool_calls=60,
                max_writer_output_bytes=60_000,
                max_handoffs=1,
                telemetry_tool_call_count=None,
                validation_timeout_seconds=None,
                json=True,
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = cmd_work_units(args)
            payload = json.loads(stdout.getvalue())

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload["gate"]["status"], "passed")
        self.assertEqual(payload["changed_files"], ["py/a.py"])


def init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test User")
    write(path / "py" / "a.py", "old\n")
    git(path, "add", "py/a.py")
    git(path, "commit", "-m", "base")
    return path


def artifact(units: list[dict]) -> dict:
    return {"schema_version": 2, "plan_path": None, "bd_epic_id": "bd-1", "work_units": units}


def unit(
    unit_id: str,
    allowed_files: list[str],
    *,
    blocked_files: list[str] | None = None,
    validation_commands: list[str] | None = None,
) -> dict:
    return {
        "id": unit_id,
        "title": unit_id,
        "goal": "goal",
        "depends_on": [],
        "context_files": [],
        "allowed_files": allowed_files,
        "blocked_files": blocked_files or [],
        "acceptance_criteria": ["passes"],
        "validation_commands": validation_commands or [],
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


def writer_return(unit_id: str, *, tool_calls: int) -> str:
    return json.dumps(
        {
            "work_unit_id": unit_id,
            "tool_calls": tool_calls,
            "output_bytes": 20,
            "handoff": False,
            "handoff_count": 0,
            "summary": "done",
        }
    )


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


if __name__ == "__main__":
    unittest.main()
