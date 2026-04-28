"""Post-run telemetry extracted from backend output streams.

The runner already captures backend stdout/stderr.  This module keeps the
instrumentation cheap by deriving tool buckets, repeated reads, handoff markers,
and cache usage from that captured stream instead of adding a second observer.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping


TOOL_CATEGORIES: tuple[str, ...] = (
    "read",
    "search",
    "shell-rg",
    "shell-bd",
    "shell-git",
    "shell-test",
    "edit",
    "web",
    "skill",
)

_MARKERS = {
    "needs_context": re.compile(r"(?<![A-Z0-9_])NEEDS_CONTEXT(?![A-Z0-9_])"),
    "needs_research": re.compile(r"(?<![A-Z0-9_])NEEDS_RESEARCH(?![A-Z0-9_])"),
    "unverified": re.compile(r"\[UNVERIFIED\]"),
}

_SHELL_PREFIX_RE = r"(?:^|[;&|()]\s*)"
_SHELL_READ_COMMANDS = {
    "bat",
    "cat",
    "find",
    "head",
    "jq",
    "less",
    "ls",
    "nl",
    "pwd",
    "sed",
    "stat",
    "tail",
    "tree",
    "wc",
}
_SHELL_SEARCH_COMMANDS = {"ag", "fd", "find", "grep", "ripgrep"}
_SHELL_EDIT_COMMANDS = {
    "cp",
    "gofmt",
    "mv",
    "perl",
    "prettier",
    "python",
    "python3",
    "ruff",
    "rustfmt",
    "touch",
}
_PATH_SUFFIXES = (
    ".bash",
    ".c",
    ".cc",
    ".cfg",
    ".cpp",
    ".css",
    ".go",
    ".h",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsonl",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".rb",
    ".rs",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
)


def analyze_backend_output(
    text: str,
    *,
    role: str | None = None,
    stage_id: str | None = None,
    unit_id: str | None = None,
) -> dict[str, Any]:
    """Return a JSON-serializable observation details payload."""

    events = list(_iter_json_lines(text))
    calls = _extract_tool_calls(events)
    inferred_unit_id = unit_id or _extract_unit_id(text)
    resolved_stage_id = stage_id or role

    category_counts: Counter[str] = Counter({category: 0 for category in TOOL_CATEGORIES})
    repeated_reads: Counter[str] = Counter()
    first_edit_index: int | None = None
    first_test_index: int | None = None
    source_read_count = 0
    bd_show_count = 0
    uncategorized_count = 0

    for index, call in enumerate(calls, start=1):
        category = _categorize_tool_call(call)
        if category in TOOL_CATEGORIES:
            category_counts[category] += 1
        else:
            uncategorized_count += 1

        if category == "edit" and first_edit_index is None:
            first_edit_index = index
        if category == "shell-test" and first_test_index is None:
            first_test_index = index

        command = _call_command(call)
        if command and _is_bd_show(command):
            bd_show_count += 1

        if category == "read":
            file_paths = _read_file_paths(call)
            if file_paths:
                source_read_count += 1
                for file_path in file_paths:
                    repeated_reads[file_path] += 1

    token_usage = _extract_token_usage(events)
    markers = {
        f"{name}_count": len(pattern.findall(text))
        for name, pattern in _MARKERS.items()
    }

    return {
        "role": role,
        "stage_id": resolved_stage_id,
        "unit_id": inferred_unit_id,
        "structured_event_count": len(events),
        "tool_call_count": len(calls),
        "tool_category_counts": dict(category_counts),
        "uncategorized_tool_count": uncategorized_count,
        "repeated_read_histogram": [
            {"file_path": file_path, "count": count}
            for file_path, count in sorted(repeated_reads.items())
            if count > 1
        ],
        "source_read_count": source_read_count,
        "bd_show_count": bd_show_count,
        "first_edit_tool_call_index": first_edit_index,
        "first_test_tool_call_index": first_test_index,
        "markers": markers,
        "token_usage": token_usage,
    }


def analyze_backend_output_file(
    path: Path,
    *,
    role: str | None = None,
    stage_id: str | None = None,
    unit_id: str | None = None,
) -> dict[str, Any]:
    return analyze_backend_output(
        path.read_text(encoding="utf-8", errors="replace"),
        role=role,
        stage_id=stage_id,
        unit_id=unit_id,
    )


def _iter_json_lines(text: str) -> Iterable[dict[str, Any]]:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or not stripped.startswith("{"):
            continue
        try:
            value = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            yield value


def _extract_tool_calls(events: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    seen: set[str] = set()
    for event in events:
        for obj in _walk_dicts(event):
            obj_type = str(obj.get("type") or "")
            name = obj.get("name") or obj.get("tool_name")
            call_id = obj.get("call_id") or obj.get("id") or obj.get("tool_call_id")

            if obj_type not in {"function_call", "tool_use"} or not isinstance(name, str):
                continue

            key = str(call_id or f"{len(calls)}:{name}:{obj.get('arguments') or obj.get('input')}")
            if key in seen:
                continue
            seen.add(key)

            raw_input = obj.get("arguments")
            if raw_input is None:
                raw_input = obj.get("input")
            calls.append(
                {
                    "name": name,
                    "input": _decode_input(raw_input),
                    "id": call_id,
                }
            )
    return calls


def _walk_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_dicts(child)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def _decode_input(raw: Any) -> Any:
    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return raw
    return raw


def _categorize_tool_call(call: Mapping[str, Any]) -> str | None:
    name = str(call.get("name") or "")
    normalized = name.lower().replace("_", "-")

    if normalized in {"read", "view-image"} or normalized.endswith(".read"):
        return "read"
    if normalized in {"grep", "glob", "search"} or "search" in normalized:
        return "web" if "web" in normalized else "search"
    if normalized in {"edit", "write", "multiedit", "apply-patch"} or "apply-patch" in normalized:
        return "edit"
    if "web" in normalized or normalized in {"webfetch", "websearch"}:
        return "web"
    if "skill" in normalized:
        return "skill"

    command = _call_command(call)
    if command is not None:
        return _categorize_shell_command(command)

    return None


def _call_command(call: Mapping[str, Any]) -> str | None:
    value = call.get("input")
    if isinstance(value, Mapping):
        for key in ("cmd", "command", "script"):
            command = value.get(key)
            if isinstance(command, str) and command.strip():
                return command
    elif isinstance(value, str) and value.strip():
        return value
    return None


def _categorize_shell_command(command: str) -> str | None:
    lowered = command.strip().lower()
    if _matches_shell_command(lowered, "bd"):
        return "shell-bd"
    if _matches_shell_command(lowered, "git"):
        return "shell-git"
    if _matches_shell_command(lowered, "rg"):
        return "shell-rg"
    if _looks_like_test_command(lowered):
        return "shell-test"

    first = _first_shell_word(lowered)
    if first in _SHELL_SEARCH_COMMANDS:
        return "search"
    if first in _SHELL_READ_COMMANDS:
        return "read"
    if first in _SHELL_EDIT_COMMANDS and _looks_like_edit_command(lowered):
        return "edit"
    return None


def _matches_shell_command(command: str, executable: str) -> bool:
    return re.search(_SHELL_PREFIX_RE + re.escape(executable) + r"\b", command) is not None


def _first_shell_word(command: str) -> str | None:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()
    for token in tokens:
        if token in {"&&", "||", "|", ";"}:
            continue
        token = token.rsplit("/", 1)[-1]
        return token
    return None


def _looks_like_test_command(command: str) -> bool:
    patterns = (
        r"\bgo\s+test\b",
        r"\bcargo\s+(?:test|nextest)\b",
        r"\bpython3?\s+-m\s+(?:unittest|pytest)\b",
        r"\bpytest\b",
        r"\b(?:npm|pnpm|yarn)\s+(?:run\s+)?(?:test|vitest|jest)\b",
        r"\b(?:bundle\s+exec\s+)?rspec\b",
        r"\bmake\s+(?:.*\s)?test\b",
        r"\bjust\s+(?:.*\s)?test\b",
        r"\bbats\b",
        r"\bctest\b",
        r"\bswift\s+test\b",
        r"\bxcodebuild\b.*\btest\b",
        r"\bmvn\s+test\b",
        r"\bgradle\s+test\b",
        r"\b./scripts/smoke\.sh\b",
    )
    return any(re.search(pattern, command) for pattern in patterns)


def _looks_like_edit_command(command: str) -> bool:
    return bool(
        re.search(r"(?:^|\s)(?:-w|-i|--write|--fix)(?:\s|$)", command)
        or re.search(r"\b(?:gofmt|rustfmt|prettier|touch|mv|cp)\b", command)
    )


def _is_bd_show(command: str) -> bool:
    return re.search(_SHELL_PREFIX_RE + r"bd\s+show\b", command.strip().lower()) is not None


def _read_file_paths(call: Mapping[str, Any]) -> list[str]:
    value = call.get("input")
    paths: list[str] = []

    if isinstance(value, Mapping):
        for key in ("file_path", "path"):
            raw = value.get(key)
            if isinstance(raw, str):
                paths.append(raw)
        for key in ("file_paths", "paths"):
            raw_paths = value.get(key)
            if isinstance(raw_paths, list):
                paths.extend(str(path) for path in raw_paths if isinstance(path, str))

    command = _call_command(call)
    if command:
        paths.extend(_paths_from_shell_command(command))

    return sorted({_clean_path(path) for path in paths if _clean_path(path)})


def _paths_from_shell_command(command: str) -> list[str]:
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = command.split()

    paths: list[str] = []
    for token in tokens:
        cleaned = _clean_path(token)
        if not cleaned or cleaned in {"&&", "||", "|", ";"}:
            continue
        if cleaned.startswith("-") or cleaned.startswith("{") or cleaned.startswith("$("):
            continue
        if cleaned in _SHELL_READ_COMMANDS or cleaned in _SHELL_SEARCH_COMMANDS:
            continue
        if _path_like(cleaned):
            paths.append(cleaned)
    return paths


def _clean_path(path: str) -> str:
    cleaned = path.strip().strip("\"'`")
    cleaned = cleaned.rstrip(",:;)")
    if cleaned.startswith("file://"):
        cleaned = cleaned[len("file://") :]
    return cleaned


def _path_like(token: str) -> bool:
    if not token or token.startswith("http://") or token.startswith("https://"):
        return False
    if re.fullmatch(r"\d+(?:,\d+)?p?", token):
        return False
    if "/" in token and not any(ch in token for ch in "*?[]{}"):
        return True
    return token.endswith(_PATH_SUFFIXES)


def _extract_unit_id(text: str) -> str | None:
    for pattern in (
        r'"work_unit_id"\s*:\s*"([^"]+)"',
        r'"unit_id"\s*:\s*"([^"]+)"',
        r"\bwork_unit_id=([A-Za-z0-9._:-]+)",
        r"\bunit_id=([A-Za-z0-9._:-]+)",
    ):
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def _extract_token_usage(events: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    for event in events:
        for obj in _walk_dicts(event):
            usage = _usage_from_object(obj)
            if not usage:
                continue
            signature = json.dumps(usage, sort_keys=True, separators=(",", ":"))
            if signature in seen:
                continue
            seen.add(signature)
            candidates.append(usage)

    if not candidates:
        return _empty_token_usage()

    best = max(candidates, key=_usage_weight)
    input_tokens = _int_or_none(best.get("input_tokens") or best.get("prompt_tokens"))
    output_tokens = _int_or_none(best.get("output_tokens") or best.get("completion_tokens"))
    cache_read = _int_or_none(
        best.get("cache_read_input_tokens")
        or best.get("cached_input_tokens")
        or best.get("cache_read_tokens")
    )
    cache_creation = _int_or_none(
        best.get("cache_creation_input_tokens") or best.get("cache_creation_tokens")
    )

    ratio = _cache_hit_ratio(
        input_tokens,
        cache_read,
        cache_creation,
        anthropic_style=(
            "cache_read_input_tokens" in best or "cache_creation_input_tokens" in best
        ),
    )
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_input_tokens": cache_read,
        "cache_read_input_tokens": cache_read,
        "cache_creation_input_tokens": cache_creation,
        "cache_hit_ratio": ratio,
    }


def _usage_from_object(obj: Mapping[str, Any]) -> dict[str, Any] | None:
    total_usage = obj.get("total_token_usage")
    if isinstance(total_usage, Mapping):
        return dict(total_usage)

    usage = obj.get("usage")
    if isinstance(usage, Mapping):
        return dict(usage)

    token_keys = {
        "input_tokens",
        "prompt_tokens",
        "output_tokens",
        "completion_tokens",
        "cached_input_tokens",
        "cache_read_input_tokens",
        "cache_creation_input_tokens",
    }
    if any(key in obj for key in token_keys):
        return {key: obj.get(key) for key in token_keys if key in obj}
    return None


def _usage_weight(usage: Mapping[str, Any]) -> int:
    return sum(
        value
        for value in (
            _int_or_none(usage.get("input_tokens") or usage.get("prompt_tokens")),
            _int_or_none(usage.get("output_tokens") or usage.get("completion_tokens")),
            _int_or_none(usage.get("cached_input_tokens") or usage.get("cache_read_input_tokens")),
            _int_or_none(usage.get("cache_creation_input_tokens")),
        )
        if value is not None
    )


def _cache_hit_ratio(
    input_tokens: int | None,
    cache_read: int | None,
    cache_creation: int | None,
    *,
    anthropic_style: bool,
) -> float | None:
    if cache_read is None:
        return None
    if anthropic_style:
        denominator = (input_tokens or 0) + (cache_read or 0) + (cache_creation or 0)
    else:
        denominator = input_tokens or 0
        if denominator and cache_read > denominator:
            denominator += cache_read
    if denominator <= 0:
        return None
    return round(cache_read / denominator, 6)


def _empty_token_usage() -> dict[str, Any]:
    return {
        "input_tokens": None,
        "output_tokens": None,
        "cached_input_tokens": None,
        "cache_read_input_tokens": None,
        "cache_creation_input_tokens": None,
        "cache_hit_ratio": None,
    }


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract swarm-run observation details")
    parser.add_argument("output_file", type=Path)
    parser.add_argument("--role")
    parser.add_argument("--stage-id")
    parser.add_argument("--unit-id")
    args = parser.parse_args(argv)

    try:
        details = analyze_backend_output_file(
            args.output_file,
            role=args.role,
            stage_id=args.stage_id,
            unit_id=args.unit_id,
        )
    except Exception as exc:  # noqa: BLE001 - runner telemetry must be fail-open.
        details = {
            "role": args.role,
            "stage_id": args.stage_id or args.role,
            "unit_id": args.unit_id,
            "structured_event_count": 0,
            "tool_call_count": 0,
            "tool_category_counts": {category: 0 for category in TOOL_CATEGORIES},
            "uncategorized_tool_count": 0,
            "repeated_read_histogram": [],
            "source_read_count": 0,
            "bd_show_count": 0,
            "first_edit_tool_call_index": None,
            "first_test_tool_call_index": None,
            "markers": {
                "needs_context_count": 0,
                "needs_research_count": 0,
                "unverified_count": 0,
            },
            "token_usage": _empty_token_usage(),
            "error": str(exc),
        }

    json.dump(details, sys.stdout, sort_keys=True, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
