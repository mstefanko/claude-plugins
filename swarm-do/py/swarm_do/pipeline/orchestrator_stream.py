"""Parse bounded stage lifecycle markers from orchestrator output."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


_MARKER_RE = re.compile(r"^(STAGE_COMPLETE|STAGE_FAILED)\s+(\{.*\})\s*$")
_MAX_MARKER_JSON_CHARS = 8192


@dataclass(frozen=True)
class StageMarker:
    kind: str
    stage_id: str
    result_path: str | None = None
    failure_kind: str | None = None
    notes: str | None = None
    commit_subject: str | None = None
    summary: str | None = None
    raw: Mapping[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "stage_id": self.stage_id,
            "result_path": self.result_path,
            "failure_kind": self.failure_kind,
            "notes": self.notes,
            "commit_subject": self.commit_subject,
            "summary": self.summary,
            "raw": dict(self.raw or {}),
        }


def parse_stage_markers(text: str) -> list[StageMarker]:
    markers: list[StageMarker] = []
    for line in text.splitlines():
        marker = parse_stage_marker_line(line)
        if marker is not None:
            markers.append(marker)
    return markers


def parse_stage_marker_line(line: str) -> StageMarker | None:
    match = _MARKER_RE.match(line.strip())
    if match is None:
        return None
    kind, payload_text = match.groups()
    if len(payload_text) > _MAX_MARKER_JSON_CHARS:
        return None
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    stage_id = payload.get("stage_id")
    if not isinstance(stage_id, str) or not stage_id:
        return None
    if kind == "STAGE_COMPLETE":
        result_path = payload.get("result_path")
        if not isinstance(result_path, str) or not result_path:
            return None
        return StageMarker(
            kind="complete",
            stage_id=stage_id,
            result_path=result_path,
            commit_subject=_optional_str(payload.get("commit_subject")),
            summary=_optional_str(payload.get("summary")),
            raw=payload,
        )
    failure_kind = payload.get("failure_kind")
    return StageMarker(
        kind="failed",
        stage_id=stage_id,
        failure_kind=failure_kind if isinstance(failure_kind, str) and failure_kind else "stage_failed",
        notes=_optional_str(payload.get("notes")),
        raw=payload,
    )


def parse_transcript_task_invocations(path: Path) -> list[dict[str, Any]]:
    """Best-effort fallback: extract Agent/Task tool-use inputs from a JSONL transcript."""

    invocations: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return invocations
    for line in lines:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        for block in _content_blocks(row):
            if not isinstance(block, Mapping):
                continue
            if block.get("type") != "tool_use" or block.get("name") not in {"Agent", "Task"}:
                continue
            payload = block.get("input")
            invocations.append(dict(payload) if isinstance(payload, Mapping) else {})
    return invocations


def _content_blocks(row: Any) -> Iterable[Mapping[str, Any]]:
    if not isinstance(row, Mapping):
        return ()
    message = row.get("message") if isinstance(row.get("message"), Mapping) else row
    content = message.get("content") if isinstance(message, Mapping) else None
    if isinstance(content, list):
        return [block for block in content if isinstance(block, Mapping)]
    return ()


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = ["StageMarker", "parse_stage_marker_line", "parse_stage_markers", "parse_transcript_task_invocations"]
