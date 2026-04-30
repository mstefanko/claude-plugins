from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.claude_transcript_diagnostics import (
    diagnose_launch,
    encode_project_path,
    load_transcript_diagnostics,
    parse_transcript,
)
from swarm_do.pipeline.paths import REPO_ROOT


FIXTURE_DIR = REPO_ROOT / "py" / "swarm_do" / "pipeline" / "tests" / "fixtures" / "claude_transcripts"


class ClaudeTranscriptDiagnosticsTests(unittest.TestCase):
    def test_encode_project_path_preserves_leading_dash_and_dot_as_dash(self) -> None:
        encoded = encode_project_path("/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins/swarm-do")

        self.assertEqual(encoded, "-Users-mstefanko--claude-plugins-marketplaces-mstefanko-plugins-swarm-do")

    def test_direct_lookup_finds_transcript(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            projects = Path(td) / "projects"
            cwd = "/tmp/swarm-do-sensitive-path-probe"
            session_id = "session-1"
            transcript = projects / encode_project_path(cwd) / f"{session_id}.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text((FIXTURE_DIR / "success.jsonl").read_text(encoding="utf-8"), encoding="utf-8")

            diagnostics = load_transcript_diagnostics(session_id, launcher_cwd=cwd, projects_dir=projects)

            self.assertTrue(diagnostics.transcript_found)
            self.assertEqual(diagnostics.transcript_path, transcript)
            self.assertEqual(diagnostics.tool_errors, ())

    def test_missing_transcript_is_diagnostic_loss_not_error(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            diagnostics = load_transcript_diagnostics("missing-session", launcher_cwd="/tmp/missing", projects_dir=Path(td))

            self.assertFalse(diagnostics.transcript_found)
            self.assertIsNone(diagnostics.transcript_path)

    def test_write_disabled_fixture_extracts_tool_error(self) -> None:
        diagnostics = parse_transcript(FIXTURE_DIR / "write-disabled.jsonl", session_id="session-1")

        self.assertTrue(diagnostics.transcript_found)
        self.assertEqual(len(diagnostics.tool_errors), 1)
        diagnostic = diagnostics.tool_errors[0]
        self.assertEqual(diagnostic.tool_name, "Write")
        self.assertEqual(diagnostic.file_path, "/tmp/swarm-do/write-target.txt")
        self.assertEqual(diagnostic.error_kind, "tool_disabled")
        self.assertIn("Write exists but is not enabled", diagnostic.message_excerpt)
        self.assertEqual(diagnostics.disabled_tool_hits[0], diagnostic)

    def test_malformed_jsonl_keeps_valid_sensitive_path_error(self) -> None:
        diagnostics = parse_transcript(FIXTURE_DIR / "malformed-mixed.jsonl", session_id="session-1")

        self.assertEqual(diagnostics.parse_errors, 1)
        self.assertEqual(len(diagnostics.tool_errors), 1)
        self.assertEqual(diagnostics.tool_errors[0].tool_name, "Edit")
        self.assertEqual(diagnostics.tool_errors[0].error_kind, "sensitive_path_blocked")

    def test_long_content_is_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            transcript = Path(td) / "long.jsonl"
            transcript.write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "type": "assistant",
                                "message": {
                                    "role": "assistant",
                                    "content": [
                                        {
                                            "type": "tool_use",
                                            "id": "toolu_1",
                                            "name": "Write",
                                            "input": {"file_path": "/tmp/x"},
                                        }
                                    ],
                                },
                            }
                        ),
                        json.dumps(
                            {
                                "type": "user",
                                "message": {
                                    "role": "user",
                                    "content": [
                                        {
                                            "type": "tool_result",
                                            "tool_use_id": "toolu_1",
                                            "is_error": True,
                                            "content": "Error: " + ("x" * 900),
                                        }
                                    ],
                                },
                            }
                        ),
                    ]
                ),
                encoding="utf-8",
            )

            diagnostics = parse_transcript(transcript, session_id="session-1")

            self.assertLessEqual(len(diagnostics.tool_errors[0].message_excerpt), 500)
            self.assertTrue(diagnostics.tool_errors[0].message_excerpt.endswith("..."))

    def test_diagnose_launch_uses_recorded_launcher_cwd_first(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            projects = Path(td) / "projects"
            launcher_cwd = "/tmp/swarm-do-launcher"
            session_id = "session-2"
            transcript = projects / encode_project_path(launcher_cwd) / f"{session_id}.jsonl"
            transcript.parent.mkdir(parents=True)
            transcript.write_text((FIXTURE_DIR / "write-disabled.jsonl").read_text(encoding="utf-8"), encoding="utf-8")

            diagnostics = diagnose_launch(
                {"stdout": json.dumps({"type": "result", "session_id": session_id})},
                {"launcher_cwd": launcher_cwd, "real_repo_root": "/Users/test/.claude/plugins/swarm-do"},
                projects_dir=projects,
            )

            self.assertTrue(diagnostics.transcript_found)
            self.assertEqual(diagnostics.tool_errors[0].tool_name, "Write")

    def test_canonical_tripwire_matches_encoded_project_path_case_insensitively(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            transcript = Path(td) / "encoded-leak.jsonl"
            source = "/Users/mstefanko/.claude/plugins/marketplaces/mstefanko-plugins/swarm-do"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "toolu_1",
                                    "is_error": True,
                                    "content": f"cwd={encode_project_path(source).upper()}",
                                }
                            ],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            diagnostics = parse_transcript(transcript, session_id="session-encoded", sensitive_path_patterns=[source])

            self.assertEqual(len(diagnostics.canonical_path_hits), 1)
            self.assertEqual(diagnostics.canonical_path_hits[0].error_kind, "canonical_path_leaked")

    def test_canonical_tripwire_matches_generic_encoded_claude_segment(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            transcript = Path(td) / "generic-encoded-leak.jsonl"
            transcript.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "toolu_1",
                                    "is_error": True,
                                    "content": "project=-USERS-OPERATOR--CLAUDE-PLUGINS-SWARM-DO",
                                }
                            ],
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            diagnostics = parse_transcript(transcript, session_id="session-generic", sensitive_path_patterns=["/.claude/"])

            self.assertEqual(len(diagnostics.canonical_path_hits), 1)
            self.assertEqual(diagnostics.canonical_path_hits[0].error_kind, "canonical_path_leaked")


if __name__ == "__main__":
    unittest.main()
