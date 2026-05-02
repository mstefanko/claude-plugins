"""Parser for Claude ``--output-format stream-json`` NDJSON frames."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping


@dataclass
class StreamChunk:
    kind: Literal["assistant_text", "result", "ignored", "malformed"]
    text: str = ""
    raw_frame: Mapping[str, Any] | None = None
    parse_error: str | None = None
    frame_type: str | None = None


class ClaudeStreamParser:
    def __init__(self) -> None:
        self._frames_seen = 0
        self._parse_error_count = 0
        self._first_parse_error: str | None = None
        self._final_result_seen = False
        self._ignored_frame_types: dict[str, int] = {}

    def feed_line(self, line: str) -> StreamChunk:
        if not line.strip():
            return StreamChunk(kind="ignored")
        try:
            frame = json.loads(line)
        except json.JSONDecodeError as exc:
            message = str(exc)
            self._parse_error_count += 1
            if self._first_parse_error is None:
                self._first_parse_error = message
            return StreamChunk(kind="malformed", parse_error=message)
        self._frames_seen += 1
        if not isinstance(frame, Mapping):
            self._count_ignored("non_object")
            return StreamChunk(kind="ignored", frame_type="non_object")
        frame_type = frame.get("type")
        frame_type_text = frame_type if isinstance(frame_type, str) and frame_type else "unknown"
        if frame_type_text == "assistant":
            text = self._next_assistant_text(frame)
            if text is None:
                self._count_ignored("assistant")
                return StreamChunk(kind="ignored", frame_type="assistant")
            return StreamChunk(kind="assistant_text", text=text, frame_type="assistant")
        if frame_type_text == "result":
            self._final_result_seen = True
            return StreamChunk(kind="result", raw_frame=frame, frame_type="result")
        self._count_ignored(frame_type_text)
        return StreamChunk(kind="ignored", frame_type=frame_type_text)

    def metadata(self) -> dict[str, Any]:
        return {
            "frames_seen": self._frames_seen,
            "parse_error_count": self._parse_error_count,
            "first_parse_error": self._first_parse_error,
            "final_result_seen": self._final_result_seen,
            "ignored_frame_types": dict(self._ignored_frame_types),
        }

    def _next_assistant_text(self, frame: Mapping[str, Any]) -> str | None:
        message = frame.get("message")
        content = message.get("content") if isinstance(message, Mapping) else None
        if not isinstance(content, list):
            return None
        texts: list[str] = []
        for block in content:
            if not isinstance(block, Mapping):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str):
                texts.append(str(block["text"]))
            elif isinstance(block.get("type"), str):
                self._count_ignored(str(block["type"]))
        if not texts:
            return None
        return "\n".join(texts)

    def _count_ignored(self, frame_type: str) -> None:
        self._ignored_frame_types[frame_type] = self._ignored_frame_types.get(frame_type, 0) + 1


__all__ = ["ClaudeStreamParser", "StreamChunk"]
