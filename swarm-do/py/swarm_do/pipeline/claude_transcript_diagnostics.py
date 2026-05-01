"""Best-effort Claude Code transcript diagnostics for silent launcher failures."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping


MAX_EXCERPT_CHARS = 500
_BARE_CLAUDE_PATTERN = "/.claude/"
_PATTERN_SOURCE_BARE_CLAUDE = "bare_claude"
_PATTERN_SOURCE_SOURCE_ROOT = "source_root"
_FIELD_ROLE_PATH = "path"
_FIELD_ROLE_COMMAND = "command"
_FIELD_ROLE_CONTENT = "content"
_FIELD_ROLE_OTHER = "other"
# Tool input field-role map. Add new Claude Code tool field names here when
# their payload shape changes, so unknown narrative fields stay unscanned.
_PATH_FIELD_NAMES = frozenset({"file_path", "path", "notebook_path"})
_TOOL_FILE_PATH_NAMES = frozenset({"file_path", "path"})
_COMMAND_FIELD_NAMES = frozenset({"command"})
_CONTENT_FIELD_NAMES = frozenset(
    {"content", "old_string", "new_string", "pattern", "prompt"}
)


@dataclass(frozen=True)
class _PatternEntry:
    pattern: str
    source: str


@dataclass(frozen=True)
class _PatternSets:
    path_patterns: tuple[str, ...]
    command_patterns: tuple[str, ...]
    content_patterns: tuple[str, ...]


@dataclass(frozen=True)
class ToolErrorDiagnostic:
    tool_name: str | None
    tool_use_id: str | None
    file_path: str | None
    is_error: bool
    error_kind: str
    message_excerpt: str
    field_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_use_id": self.tool_use_id,
            "file_path": self.file_path,
            "is_error": self.is_error,
            "error_kind": self.error_kind,
            "message_excerpt": self.message_excerpt,
            "field_path": self.field_path,
        }


@dataclass(frozen=True)
class TranscriptDiagnostics:
    session_id: str | None
    transcript_path: Path | None
    transcript_found: bool
    parse_errors: int
    tool_errors: tuple[ToolErrorDiagnostic, ...]
    canonical_path_hits: tuple[ToolErrorDiagnostic, ...]
    sensitive_path_hits: tuple[ToolErrorDiagnostic, ...]
    disabled_tool_hits: tuple[ToolErrorDiagnostic, ...]
    last_error_summary: str | None

    def primary_tool_error(self) -> ToolErrorDiagnostic | None:
        if self.canonical_path_hits:
            return self.canonical_path_hits[-1]
        if self.sensitive_path_hits:
            return self.sensitive_path_hits[-1]
        if self.disabled_tool_hits:
            return self.disabled_tool_hits[-1]
        if self.tool_errors:
            return self.tool_errors[-1]
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "transcript_path": str(self.transcript_path) if self.transcript_path else None,
            "transcript_found": self.transcript_found,
            "parse_errors": self.parse_errors,
            "tool_errors": [item.to_dict() for item in self.tool_errors],
            "canonical_path_hits": [item.to_dict() for item in self.canonical_path_hits],
            "sensitive_path_hits": [item.to_dict() for item in self.sensitive_path_hits],
            "disabled_tool_hits": [item.to_dict() for item in self.disabled_tool_hits],
            "last_error_summary": self.last_error_summary,
        }


def encode_project_path(path: str) -> str:
    """Encode a cwd string the way local Claude Code project dirs are observed."""

    return "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in path)


def project_dir_candidates(path: str) -> tuple[str, ...]:
    values = [encode_project_path(path), path.replace("/", "-")]
    return tuple(dict.fromkeys(value for value in values if value))


def session_id_from_stdout(stdout: str) -> str | None:
    try:
        payload = json.loads(stdout)
    except Exception:
        return None
    if not isinstance(payload, Mapping):
        return None
    value = payload.get("session_id")
    return value if isinstance(value, str) and value else None


def load_transcript_diagnostics(
    session_id: str | None,
    *,
    launcher_cwd: str | None,
    fallback_cwds: Iterable[str] = (),
    sensitive_path_patterns: Iterable[str] = (),
    projects_dir: Path | None = None,
) -> TranscriptDiagnostics:
    if not session_id:
        return _empty(session_id=session_id)
    root = projects_dir or Path.home() / ".claude" / "projects"
    path = locate_transcript(session_id, launcher_cwd=launcher_cwd, fallback_cwds=fallback_cwds, projects_dir=root)
    if path is None:
        return _empty(session_id=session_id)
    return parse_transcript(path, session_id=session_id, sensitive_path_patterns=sensitive_path_patterns)


def diagnose_launch(
    launcher_result: Mapping[str, Any] | None,
    command_metadata: Mapping[str, Any],
    *,
    projects_dir: Path | None = None,
) -> TranscriptDiagnostics:
    stdout = ""
    if launcher_result is not None and isinstance(launcher_result.get("stdout"), str):
        stdout = str(launcher_result.get("stdout") or "")
    session_id = session_id_from_stdout(stdout)
    launcher_cwd = command_metadata.get("launcher_cwd")
    fallback_cwds = [
        value
        for value in (command_metadata.get("real_repo_root"), command_metadata.get("cwd"))
        if isinstance(value, str) and value
    ]
    sensitive_patterns = _diagnostic_sensitive_patterns(command_metadata)
    return load_transcript_diagnostics(
        session_id,
        launcher_cwd=launcher_cwd if isinstance(launcher_cwd, str) else None,
        fallback_cwds=fallback_cwds,
        sensitive_path_patterns=sensitive_patterns,
        projects_dir=projects_dir,
    )


def locate_transcript(
    session_id: str,
    *,
    launcher_cwd: str | None,
    fallback_cwds: Iterable[str] = (),
    projects_dir: Path | None = None,
) -> Path | None:
    root = projects_dir or Path.home() / ".claude" / "projects"
    cwd_values = [launcher_cwd, *fallback_cwds]
    for cwd in cwd_values:
        if not cwd:
            continue
        for candidate_dir in project_dir_candidates(str(cwd)):
            candidate = root / candidate_dir / f"{session_id}.jsonl"
            if candidate.is_file():
                return candidate
    try:
        for candidate in root.glob(f"*/{session_id}.jsonl"):
            if candidate.is_file():
                return candidate
    except OSError:
        return None
    return None


def parse_transcript(
    path: Path,
    *,
    session_id: str | None = None,
    sensitive_path_patterns: Iterable[str] = (),
) -> TranscriptDiagnostics:
    tool_uses: dict[str, dict[str, str | None]] = {}
    tool_errors: list[ToolErrorDiagnostic] = []
    canonical_hits: list[ToolErrorDiagnostic] = []
    parse_errors = 0
    pattern_sets = _coerce_pattern_sets(sensitive_path_patterns)
    try:
        with path.open("r", encoding="utf-8", errors="replace") as lines:
            for line in lines:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    parse_errors += 1
                    continue
                if not isinstance(row, Mapping):
                    parse_errors += 1
                    continue
                role = _message_role(row)
                blocks = _content_blocks(row)
                if role == "assistant":
                    for block in blocks:
                        if block.get("type") != "tool_use":
                            continue
                        tool_id = block.get("id")
                        if not isinstance(tool_id, str) or not tool_id:
                            continue
                        file_path = _tool_file_path(block.get("input"))
                        tool_uses[tool_id] = {
                            "tool_name": block.get("name") if isinstance(block.get("name"), str) else None,
                            "file_path": file_path,
                        }
                        for field_path, field_value in _tool_input_fields(block.get("input")):
                            field_role = _tool_input_field_role(field_path)
                            role_patterns = _patterns_for_field_role(pattern_sets, field_role)
                            if not role_patterns or not _contains_canonical_path(field_value, role_patterns):
                                continue
                            canonical_hits.append(
                                ToolErrorDiagnostic(
                                    tool_name=block.get("name") if isinstance(block.get("name"), str) else None,
                                    tool_use_id=tool_id,
                                    file_path=field_value if field_role == _FIELD_ROLE_PATH else None,
                                    is_error=False,
                                    error_kind="canonical_path_leaked",
                                    message_excerpt=_excerpt(field_value),
                                    field_path=field_path,
                                )
                            )
                elif role == "user":
                    for block in blocks:
                        if block.get("type") != "tool_result":
                            continue
                        content = _flatten_content(block.get("content"))
                        is_error = bool(block.get("is_error")) or "<tool_use_error" in content.lower()
                        tool_id_value = block.get("tool_use_id")
                        tool_id = tool_id_value if isinstance(tool_id_value, str) else None
                        tool_use = tool_uses.get(tool_id or "", {})
                        if _contains_canonical_path(content, pattern_sets.content_patterns):
                            canonical_hits.append(
                                ToolErrorDiagnostic(
                                    tool_name=_string_or_none(tool_use.get("tool_name")),
                                    tool_use_id=tool_id,
                                    file_path=_string_or_none(tool_use.get("file_path")),
                                    is_error=is_error,
                                    error_kind="canonical_path_leaked",
                                    message_excerpt=_excerpt(content),
                                )
                            )
                        if not is_error:
                            continue
                        diagnostic = ToolErrorDiagnostic(
                            tool_name=_string_or_none(tool_use.get("tool_name")),
                            tool_use_id=tool_id,
                            file_path=_string_or_none(tool_use.get("file_path")),
                            is_error=is_error,
                            error_kind=classify_tool_error(content),
                            message_excerpt=_excerpt(content),
                        )
                        tool_errors.append(diagnostic)
    except OSError:
        return _empty(session_id=session_id)
    sensitive = tuple(item for item in tool_errors if item.error_kind == "sensitive_path_blocked")
    disabled = tuple(item for item in tool_errors if item.error_kind == "tool_disabled")
    canonical = tuple(canonical_hits)
    last = tool_errors[-1] if tool_errors else canonical[-1] if canonical else None
    return TranscriptDiagnostics(
        session_id=session_id,
        transcript_path=path,
        transcript_found=True,
        parse_errors=parse_errors,
        tool_errors=tuple(tool_errors),
        canonical_path_hits=canonical,
        sensitive_path_hits=sensitive,
        disabled_tool_hits=disabled,
        last_error_summary=_last_error_summary(last) if last else None,
    )


def classify_tool_error(message: str) -> str:
    lowered = message.lower()
    if "exists but is not enabled" in lowered or "no such tool available" in lowered or "tool isn't enabled" in lowered:
        return "tool_disabled"
    if "sensitive" in lowered and re.search(r"\b(file|path|write|edit)\b", lowered):
        return "sensitive_path_blocked"
    if "permission" in lowered and re.search(r"\b(denied|deny|blocked|not permitted|not allowed)\b", lowered):
        return "permission_denied"
    if "<tool_use_error" in lowered or "is_error" in lowered or "error:" in lowered:
        return "tool_error"
    return "tool_error"


def _empty(*, session_id: str | None) -> TranscriptDiagnostics:
    return TranscriptDiagnostics(
        session_id=session_id,
        transcript_path=None,
        transcript_found=False,
        parse_errors=0,
        tool_errors=(),
        canonical_path_hits=(),
        sensitive_path_hits=(),
        disabled_tool_hits=(),
        last_error_summary=None,
    )


def _message_role(row: Mapping[str, Any]) -> str | None:
    message = row.get("message")
    if isinstance(message, Mapping) and isinstance(message.get("role"), str):
        return str(message["role"])
    value = row.get("role") or row.get("type")
    return value if isinstance(value, str) else None


def _content_blocks(row: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    message = row.get("message")
    content = message.get("content") if isinstance(message, Mapping) else row.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, Mapping)]


def _tool_file_path(value: Any) -> str | None:
    for field_path, field_value in _tool_input_fields(value):
        if _field_leaf_name(field_path) in _TOOL_FILE_PATH_NAMES:
            return field_value
    return None


def _tool_input_fields(value: Any) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield "", value
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield from _tool_input_fields_at(child, str(key))
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            yield from _tool_input_fields_at(child, f"[{index}]")


def _tool_input_fields_at(value: Any, field_path: str) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield field_path, value
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield from _tool_input_fields_at(child, f"{field_path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            yield from _tool_input_fields_at(child, f"{field_path}[{index}]")


def _flatten_content(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_flatten_content(item) for item in value)
    if isinstance(value, Mapping):
        if isinstance(value.get("text"), str):
            return str(value["text"])
        if isinstance(value.get("content"), str):
            return str(value["content"])
        return json.dumps(dict(value), sort_keys=True)
    return "" if value is None else str(value)


def _excerpt(text: str) -> str:
    clean = " ".join(text.split())
    if len(clean) <= MAX_EXCERPT_CHARS:
        return clean
    return clean[: MAX_EXCERPT_CHARS - 3].rstrip() + "..."


def _last_error_summary(diagnostic: ToolErrorDiagnostic) -> str:
    tool = diagnostic.tool_name or "unknown_tool"
    return f"{tool} {diagnostic.error_kind}: {diagnostic.message_excerpt}"


def _diagnostic_sensitive_patterns(command_metadata: Mapping[str, Any]) -> _PatternSets:
    values = []
    for key in ("source_project_root", "source_git_top_level", "real_repo_root"):
        value = command_metadata.get(key)
        if isinstance(value, str) and value:
            values.append(value)
    values.append(_BARE_CLAUDE_PATTERN)
    return _coerce_pattern_sets(tuple(dict.fromkeys(values)))


def _coerce_pattern_sets(patterns: Iterable[str] | _PatternSets) -> _PatternSets:
    if isinstance(patterns, _PatternSets):
        return patterns
    entries = _canonical_patterns(patterns)
    path_patterns = _pattern_values(entries)
    content_patterns = _pattern_values(
        entry for entry in entries if entry.source != _PATTERN_SOURCE_BARE_CLAUDE
    )
    return _PatternSets(
        path_patterns=path_patterns,
        command_patterns=path_patterns,
        content_patterns=content_patterns,
    )


def _canonical_patterns(patterns: Iterable[str]) -> tuple[_PatternEntry, ...]:
    values: list[_PatternEntry] = []
    seen: set[tuple[str, str]] = set()
    for pattern in patterns:
        if not pattern:
            continue
        source = _pattern_source(pattern)
        candidates = [pattern, *project_dir_candidates(pattern)]
        for candidate in candidates:
            for value in _pattern_variants(candidate):
                key = (value, source)
                if key in seen:
                    continue
                seen.add(key)
                values.append(_PatternEntry(pattern=value, source=source))
    return tuple(values)


def _pattern_source(pattern: str) -> str:
    return (
        _PATTERN_SOURCE_BARE_CLAUDE
        if pattern == _BARE_CLAUDE_PATTERN
        else _PATTERN_SOURCE_SOURCE_ROOT
    )


def _pattern_variants(pattern: str) -> tuple[str, ...]:
    values = [pattern]
    escaped = _json_slash_escape(pattern)
    if escaped != pattern:
        values.append(escaped)
    return tuple(values)


def _pattern_values(entries: Iterable[_PatternEntry]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(entry.pattern for entry in entries if entry.pattern))


def _patterns_for_field_role(pattern_sets: _PatternSets, role: str) -> tuple[str, ...]:
    if role == _FIELD_ROLE_PATH:
        return pattern_sets.path_patterns
    if role == _FIELD_ROLE_COMMAND:
        return pattern_sets.command_patterns
    if role == _FIELD_ROLE_CONTENT:
        return pattern_sets.content_patterns
    return ()


def _tool_input_field_role(field_path: str) -> str:
    leaf = _field_leaf_name(field_path)
    if leaf in _PATH_FIELD_NAMES:
        return _FIELD_ROLE_PATH
    if leaf in _COMMAND_FIELD_NAMES:
        return _FIELD_ROLE_COMMAND
    if leaf in _CONTENT_FIELD_NAMES:
        return _FIELD_ROLE_CONTENT
    return _FIELD_ROLE_OTHER


def _field_leaf_name(field_path: str) -> str:
    leaf = field_path.rsplit(".", 1)[-1]
    return re.sub(r"\[\d+\]$", "", leaf)


def _contains_canonical_path(text: str, patterns: tuple[str, ...]) -> bool:
    if not text:
        return False
    lowered = text.lower()
    return any(pattern.lower() in lowered for pattern in patterns)


def _json_slash_escape(value: str) -> str:
    return value.replace("/", r"\/")


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


__all__ = [
    "ToolErrorDiagnostic",
    "TranscriptDiagnostics",
    "classify_tool_error",
    "diagnose_launch",
    "encode_project_path",
    "load_transcript_diagnostics",
    "locate_transcript",
    "parse_transcript",
    "project_dir_candidates",
    "session_id_from_stdout",
]
