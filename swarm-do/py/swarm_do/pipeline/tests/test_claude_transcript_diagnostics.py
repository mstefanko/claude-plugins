from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from swarm_do.pipeline.claude_transcript_diagnostics import (
    _tool_input_fields,
    diagnose_launch,
    encode_project_path,
    load_transcript_diagnostics,
    parse_transcript,
)
from swarm_do.pipeline.paths import REPO_ROOT


FIXTURE_DIR = REPO_ROOT / "py" / "swarm_do" / "pipeline" / "tests" / "fixtures" / "claude_transcripts"
SYNTHETIC_SOURCE_ROOT = "/Users/example/.dev-marketplaces/example-plugins/swarm-do"
SYNTHETIC_CLAUDE_EXAMPLE = "/Users/operator/.claude/plugins/example/swarm-do"


class ClaudeTranscriptDiagnosticsTests(unittest.TestCase):
    def test_encode_project_path_preserves_leading_dash_and_dot_as_dash(self) -> None:
        encoded = encode_project_path(SYNTHETIC_SOURCE_ROOT)

        self.assertEqual(encoded, "-Users-example--dev-marketplaces-example-plugins-swarm-do")

    def test_tool_input_fields_walks_string_leaves_in_order(self) -> None:
        payload = {
            "file_path": "/tmp/a.txt",
            "content": "body",
            "count": 3,
            "command": ["echo ok", "pwd"],
            "nested": {
                "old_string": "old",
                "flag": True,
                "none": None,
                "items": ["alpha", 2, {"new_string": "new"}],
            },
            "edits": [{"old_string": "before", "new_string": "after"}],
        }

        self.assertEqual(
            list(_tool_input_fields(payload)),
            [
                ("file_path", "/tmp/a.txt"),
                ("content", "body"),
                ("command[0]", "echo ok"),
                ("command[1]", "pwd"),
                ("nested.old_string", "old"),
                ("nested.items[0]", "alpha"),
                ("nested.items[2].new_string", "new"),
                ("edits[0].old_string", "before"),
                ("edits[0].new_string", "after"),
            ],
        )

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
            source = SYNTHETIC_SOURCE_ROOT
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

    def test_canonical_tripwire_ignores_generic_encoded_claude_segment_in_content(self) -> None:
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

            self.assertEqual(diagnostics.canonical_path_hits, ())

    def test_generic_claude_path_in_tool_result_content_is_not_flagged(self) -> None:
        diagnostics = self._parse_rows(
            [
                self._tool_result_row(
                    content=f'{{"plugin_root": "{SYNTHETIC_CLAUDE_EXAMPLE}", "ok": true}}',
                    is_error=False,
                )
            ],
            sensitive_path_patterns=["/.claude/"],
        )

        self.assertEqual(diagnostics.canonical_path_hits, ())

    def test_precise_source_root_in_tool_result_content_is_flagged(self) -> None:
        diagnostics = self._parse_rows(
            [
                self._tool_result_row(
                    content=f"canonical checkout is {SYNTHETIC_CLAUDE_EXAMPLE}",
                    is_error=False,
                )
            ],
            sensitive_path_patterns=[SYNTHETIC_CLAUDE_EXAMPLE],
        )

        self.assertEqual(len(diagnostics.canonical_path_hits), 1)
        hit = diagnostics.canonical_path_hits[0]
        self.assertEqual(hit.error_kind, "canonical_path_leaked")
        self.assertIsNone(hit.field_path)
        self.assertIn(SYNTHETIC_CLAUDE_EXAMPLE, hit.message_excerpt)

    def test_read_file_path_under_claude_projects_is_flagged(self) -> None:
        file_path = "/Users/x/.claude/projects/session.jsonl"
        diagnostics = self._parse_rows(
            [self._tool_use_row(name="Read", input_value={"file_path": file_path})],
            sensitive_path_patterns=["/.claude/"],
        )

        self.assertEqual(len(diagnostics.canonical_path_hits), 1)
        hit = diagnostics.canonical_path_hits[0]
        self.assertEqual(hit.tool_name, "Read")
        self.assertEqual(hit.file_path, file_path)
        self.assertEqual(hit.field_path, "file_path")

    def test_bash_command_under_claude_projects_is_flagged_without_file_path(self) -> None:
        command = "cat ~/.claude/projects/session.jsonl"
        diagnostics = self._parse_rows(
            [self._tool_use_row(name="Bash", input_value={"command": command})],
            sensitive_path_patterns=["/.claude/"],
        )

        self.assertEqual(len(diagnostics.canonical_path_hits), 1)
        hit = diagnostics.canonical_path_hits[0]
        self.assertEqual(hit.tool_name, "Bash")
        self.assertIsNone(hit.file_path)
        self.assertEqual(hit.field_path, "command")
        self.assertIn(command, hit.message_excerpt)

    def test_bash_command_without_sensitive_path_is_not_flagged(self) -> None:
        diagnostics = self._parse_rows(
            [self._tool_use_row(name="Bash", input_value={"command": "ls /tmp"})],
            sensitive_path_patterns=["/.claude/"],
        )

        self.assertEqual(diagnostics.canonical_path_hits, ())

    def test_safe_read_with_generic_claude_example_in_result_is_not_flagged(self) -> None:
        diagnostics = self._parse_rows(
            [
                self._tool_use_row(name="Read", input_value={"file_path": "/tmp/safe/selftest.ok.json"}),
                self._tool_result_row(content=f'{{"plugin_root": "{SYNTHETIC_CLAUDE_EXAMPLE}"}}'),
            ],
            sensitive_path_patterns=["/.claude/"],
        )

        self.assertEqual(diagnostics.canonical_path_hits, ())

    def test_write_content_with_generic_claude_example_is_not_flagged(self) -> None:
        diagnostics = self._parse_rows(
            [
                self._tool_use_row(
                    name="Write",
                    input_value={"file_path": "/tmp/example.json", "content": SYNTHETIC_CLAUDE_EXAMPLE},
                )
            ],
            sensitive_path_patterns=["/.claude/"],
        )

        self.assertEqual(diagnostics.canonical_path_hits, ())

    def test_edit_content_with_generic_claude_examples_is_not_flagged(self) -> None:
        diagnostics = self._parse_rows(
            [
                self._tool_use_row(
                    name="Edit",
                    input_value={
                        "file_path": "/tmp/example.json",
                        "old_string": SYNTHETIC_CLAUDE_EXAMPLE,
                        "new_string": f"{SYNTHETIC_CLAUDE_EXAMPLE}/next",
                    },
                )
            ],
            sensitive_path_patterns=["/.claude/"],
        )

        self.assertEqual(diagnostics.canonical_path_hits, ())

    def test_multiedit_content_with_generic_claude_examples_is_not_flagged(self) -> None:
        diagnostics = self._parse_rows(
            [
                self._tool_use_row(
                    name="MultiEdit",
                    input_value={
                        "file_path": "/tmp/example.json",
                        "edits": [
                            {
                                "old_string": SYNTHETIC_CLAUDE_EXAMPLE,
                                "new_string": f"{SYNTHETIC_CLAUDE_EXAMPLE}/next",
                            }
                        ],
                    },
                )
            ],
            sensitive_path_patterns=["/.claude/"],
        )

        self.assertEqual(diagnostics.canonical_path_hits, ())

    def test_grep_pattern_with_bare_claude_literal_is_not_flagged(self) -> None:
        diagnostics = self._parse_rows(
            [self._tool_use_row(name="Grep", input_value={"pattern": "/.claude/"})],
            sensitive_path_patterns=["/.claude/"],
        )

        self.assertEqual(diagnostics.canonical_path_hits, ())

    def test_write_content_with_precise_source_root_is_flagged(self) -> None:
        diagnostics = self._parse_rows(
            [
                self._tool_use_row(
                    name="Write",
                    input_value={"file_path": "/tmp/example.txt", "content": f"root={SYNTHETIC_SOURCE_ROOT}"},
                )
            ],
            sensitive_path_patterns=[SYNTHETIC_SOURCE_ROOT],
        )

        self.assertEqual(len(diagnostics.canonical_path_hits), 1)
        hit = diagnostics.canonical_path_hits[0]
        self.assertEqual(hit.error_kind, "canonical_path_leaked")
        self.assertIsNone(hit.file_path)
        self.assertEqual(hit.field_path, "content")

    def test_edit_old_string_with_precise_source_root_is_flagged(self) -> None:
        diagnostics = self._parse_rows(
            [
                self._tool_use_row(
                    name="Edit",
                    input_value={
                        "file_path": "/tmp/example.txt",
                        "old_string": f"root={SYNTHETIC_SOURCE_ROOT}",
                        "new_string": "root=/tmp/safe",
                    },
                )
            ],
            sensitive_path_patterns=[SYNTHETIC_SOURCE_ROOT],
        )

        self.assertEqual(len(diagnostics.canonical_path_hits), 1)
        hit = diagnostics.canonical_path_hits[0]
        self.assertEqual(hit.error_kind, "canonical_path_leaked")
        self.assertIsNone(hit.file_path)
        self.assertEqual(hit.field_path, "old_string")

    def _parse_rows(self, rows: list[dict[str, object]], *, sensitive_path_patterns: list[str]) -> object:
        with tempfile.TemporaryDirectory() as td:
            transcript = Path(td) / "transcript.jsonl"
            transcript.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
            return parse_transcript(
                transcript,
                session_id="session-generated",
                sensitive_path_patterns=sensitive_path_patterns,
            )

    def _tool_use_row(
        self,
        *,
        name: str,
        input_value: dict[str, object],
        tool_id: str = "toolu_1",
    ) -> dict[str, object]:
        return {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": tool_id, "name": name, "input": input_value}],
            },
        }

    def _tool_result_row(
        self,
        *,
        content: str,
        tool_id: str = "toolu_1",
        is_error: bool = False,
    ) -> dict[str, object]:
        return {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "is_error": is_error,
                        "content": content,
                    }
                ],
            },
        }


if __name__ == "__main__":
    unittest.main()
