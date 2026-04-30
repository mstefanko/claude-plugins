from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.claude_transcript_diagnostics import encode_project_path
from swarm_do.pipeline.paths import REPO_ROOT
from swarm_do.pipeline.phase_failure_classifier import classify_launcher_failure


FIXTURE_DIR = REPO_ROOT / "py" / "swarm_do" / "pipeline" / "tests" / "fixtures" / "claude_transcripts"


class PhaseFailureClassifierTests(unittest.TestCase):
    def test_existing_outer_artifacts_missing_is_preserved_without_suspicious_metrics(self) -> None:
        classification = classify_launcher_failure(
            {"status": "launched", "returncode": 0, "stdout": json.dumps({"type": "result", "result": "{}"}), "stderr": ""},
            {"valid": False, "partial": False},
            changed_files=["docs/x.md"],
            command_metadata={"argv": ["claude"]},
        )

        self.assertEqual(classification.failure_kind, "outer_artifacts_missing")

    def test_silent_writer_with_turns_uses_cheap_fallback_when_transcript_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            classification = classify_launcher_failure(
                {
                    "status": "launched",
                    "returncode": 0,
                    "stdout": json.dumps(
                        {
                            "type": "result",
                            "session_id": "missing-session",
                            "result": "",
                            "num_turns": 14,
                            "total_cost_usd": 0.73,
                        }
                    ),
                    "stderr": "",
                },
                {"valid": False, "partial": False},
                changed_files=[],
                command_metadata={"argv": ["claude"], "launcher_cwd": "/tmp/swarm-do"},
                projects_dir=Path(td),
            )

            self.assertEqual(classification.failure_kind, "writer_silent_with_turns")
            self.assertIn("14 turns", classification.last_error or "")

    def test_write_disabled_transcript_becomes_tool_denied(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            projects = Path(td) / "projects"
            cwd = "/tmp/swarm-do-launcher"
            session_id = "session-tool-disabled"
            transcript = projects / encode_project_path(cwd) / f"{session_id}.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text((FIXTURE_DIR / "write-disabled.jsonl").read_text(encoding="utf-8"), encoding="utf-8")

            classification = classify_launcher_failure(
                {
                    "status": "launched",
                    "returncode": 0,
                    "stdout": json.dumps({"type": "result", "session_id": session_id, "result": "", "num_turns": 14}),
                    "stderr": "",
                },
                {"valid": False, "partial": False},
                changed_files=[],
                command_metadata={"argv": ["claude"], "launcher_cwd": cwd},
                projects_dir=projects,
            )

            self.assertEqual(classification.failure_kind, "writer_tool_denied_no_artifacts")
            self.assertEqual(classification.details["tool_name"], "Write")
            self.assertEqual(classification.details["tool_error_kind"], "tool_disabled")
            self.assertIn("Write exists but is not enabled", classification.details["message_excerpt"])

    def test_sensitive_path_transcript_with_canonical_path_becomes_leak(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            projects = Path(td) / "projects"
            cwd = "/tmp/swarm-do-launcher"
            session_id = "session-sensitive"
            transcript = projects / encode_project_path(cwd) / f"{session_id}.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text((FIXTURE_DIR / "malformed-mixed.jsonl").read_text(encoding="utf-8"), encoding="utf-8")

            classification = classify_launcher_failure(
                {
                    "status": "launched",
                    "returncode": 0,
                    "stdout": json.dumps({"type": "result", "session_id": session_id, "result": "", "num_turns": 5}),
                    "stderr": "",
                },
                {"valid": False, "partial": False},
                changed_files=[],
                command_metadata={"argv": ["claude"], "launcher_cwd": cwd},
                projects_dir=projects,
            )

            self.assertEqual(classification.failure_kind, "canonical_path_leaked_in_tool_result")
            self.assertEqual(classification.details["tool_error_kind"], "canonical_path_leaked")

    def test_canonical_source_path_leak_overrides_tool_denied(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            projects = Path(td) / "projects"
            cwd = "/tmp/swarm-do-launcher"
            source_root = "/Users/test/.claude/plugins/marketplaces/example/swarm-do"
            session_id = "session-canonical-leak"
            transcript = projects / encode_project_path(cwd) / f"{session_id}.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": [
                                        {
                                            "type": "tool_use",
                                            "id": "toolu_1",
                                            "name": "Write",
                                            "input": {"file_path": f"{source_root}/docs/x.md"},
                                        }
                                    ],
                                }
                            }
                        ),
                        json.dumps(
                            {
                                "message": {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "tool_result",
                                            "tool_use_id": "toolu_1",
                                            "is_error": True,
                                            "content": f"<tool_use_error>Write denied for {source_root}/docs/x.md</tool_use_error>",
                                        }
                                    ],
                                }
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            classification = classify_launcher_failure(
                {
                    "status": "launched",
                    "returncode": 0,
                    "stdout": json.dumps({"type": "result", "session_id": session_id, "result": "", "num_turns": 4}),
                    "stderr": "",
                },
                {"valid": False, "partial": False},
                changed_files=[],
                command_metadata={
                    "argv": ["claude"],
                    "launcher_cwd": cwd,
                    "source_project_root": source_root,
                    "source_git_top_level": "/Users/test/.claude/plugins/marketplaces/example",
                },
                projects_dir=projects,
            )

            self.assertEqual(classification.failure_kind, "canonical_path_leaked_in_tool_result")
            self.assertEqual(classification.details["tool_error_kind"], "canonical_path_leaked")
            self.assertIn(source_root, classification.details["sensitive_path_excerpt"])

    def test_nonzero_returncode_remains_nonzero(self) -> None:
        classification = classify_launcher_failure(
            {"status": "launched", "returncode": 1, "stdout": "", "stderr": "boom"},
            {"valid": False, "partial": False},
            changed_files=[],
            command_metadata={"argv": ["claude"]},
        )

        self.assertEqual(classification.failure_kind, "launcher_nonzero_no_artifacts")

    def test_valid_artifacts_win_over_transcript_errors(self) -> None:
        classification = classify_launcher_failure(
            {"status": "launched", "returncode": 0, "stdout": "", "stderr": ""},
            {"valid": True, "partial": True},
            changed_files=[],
            command_metadata={"argv": ["claude"]},
        )

        self.assertEqual(classification.failure_kind, "adoptable_artifacts")


if __name__ == "__main__":
    unittest.main()
