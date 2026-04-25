"""A tiny YAML subset parser used for stock/user pipeline files.

The plugin intentionally avoids third-party dependencies. This parser supports
the subset used by pipeline YAML: mappings, lists, quoted/plain scalars, inline
lists, and simple inline maps.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any, Iterable


class YamlError(ValueError):
    pass


CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def load_yaml(path: str | Path) -> Any:
    p = Path(path)
    return loads(p.read_text(encoding="utf-8"), source=str(p))


def loads(text: str, source: str = "<string>") -> Any:
    lines: list[tuple[int, str, int]] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        if CONTROL_RE.search(raw):
            raise YamlError(f"{source}:{lineno}: control characters are not supported")
        stripped = _strip_comment(raw).rstrip()
        if not stripped.strip():
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        if indent % 2 != 0:
            raise YamlError(f"{source}:{lineno}: indentation must use multiples of two spaces")
        lines.append((indent, stripped.lstrip(" "), lineno))
    if not lines:
        return {}
    value, idx = _parse_block(lines, 0, lines[0][0], source)
    if idx != len(lines):
        _, _, lineno = lines[idx]
        raise YamlError(f"{source}:{lineno}: unexpected trailing content")
    return value


def _strip_comment(raw: str) -> str:
    in_single = False
    in_double = False
    for i, ch in enumerate(raw):
        if ch == "'" and not in_double and not _is_escaped(raw, i):
            in_single = not in_single
        elif ch == '"' and not in_single and not _is_escaped(raw, i):
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return raw[:i]
    return raw


def _parse_block(lines: list[tuple[int, str, int]], idx: int, indent: int, source: str) -> tuple[Any, int]:
    if idx >= len(lines):
        return {}, idx
    cur_indent, cur_text, lineno = lines[idx]
    if cur_indent < indent:
        return {}, idx
    if cur_indent > indent:
        raise YamlError(f"{source}:{lineno}: unexpected indentation")
    if cur_text.startswith("- "):
        return _parse_list(lines, idx, indent, source)
    return _parse_mapping(lines, idx, indent, source)


def _parse_list(lines: list[tuple[int, str, int]], idx: int, indent: int, source: str) -> tuple[list[Any], int]:
    out: list[Any] = []
    while idx < len(lines):
        cur_indent, cur_text, lineno = lines[idx]
        if cur_indent < indent:
            break
        if cur_indent != indent or not cur_text.startswith("- "):
            break
        item_text = cur_text[2:].strip()
        idx += 1
        if not item_text:
            item, idx = _parse_block(lines, idx, indent + 2, source)
            out.append(item)
            continue
        if _looks_like_mapping_entry(item_text):
            item = _parse_inline_mapping_entries(item_text, source, lineno)
            if idx < len(lines) and lines[idx][0] > indent:
                child, idx = _parse_block(lines, idx, indent + 2, source)
                if not isinstance(child, dict):
                    raise YamlError(f"{source}:{lineno}: list item continuation must be a mapping")
                item.update(child)
            out.append(item)
        else:
            out.append(_parse_scalar(item_text))
            if idx < len(lines) and lines[idx][0] > indent:
                _, _, child_lineno = lines[idx]
                raise YamlError(f"{source}:{child_lineno}: scalar list item cannot have children")
    return out, idx


def _parse_mapping(lines: list[tuple[int, str, int]], idx: int, indent: int, source: str) -> tuple[dict[str, Any], int]:
    out: dict[str, Any] = {}
    while idx < len(lines):
        cur_indent, cur_text, lineno = lines[idx]
        if cur_indent < indent:
            break
        if cur_indent != indent:
            raise YamlError(f"{source}:{lineno}: unexpected indentation")
        if cur_text.startswith("- "):
            break
        key, value_text = _split_key_value(cur_text, source, lineno)
        idx += 1
        if value_text == "":
            if idx < len(lines) and lines[idx][0] > indent:
                value, idx = _parse_block(lines, idx, indent + 2, source)
            else:
                value = {}
        else:
            value = _parse_scalar(value_text)
        out[key] = value
    return out, idx


def _split_key_value(text: str, source: str, lineno: int) -> tuple[str, str]:
    if ":" not in text:
        raise YamlError(f"{source}:{lineno}: expected key: value")
    key, value = text.split(":", 1)
    key = key.strip()
    if not key:
        raise YamlError(f"{source}:{lineno}: empty key")
    return key, value.strip()


def _looks_like_mapping_entry(text: str) -> bool:
    return re.match(r"^[A-Za-z0-9_.-]+\s*:", text) is not None


def _parse_inline_mapping_entries(text: str, source: str, lineno: int) -> dict[str, Any]:
    key, value = _split_key_value(text, source, lineno)
    return {key: _parse_scalar(value)}


def _parse_scalar(text: str) -> Any:
    if text == "":
        return ""
    if text in ("null", "~"):
        return None
    if text == "true":
        return True
    if text == "false":
        return False
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        value = ast.literal_eval(text)
        if isinstance(value, str):
            _reject_control_scalar(value)
        return value
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part.strip()) for part in _split_commas(inner)]
    if text.startswith("{") and text.endswith("}"):
        inner = text[1:-1].strip()
        if not inner:
            return {}
        out: dict[str, Any] = {}
        for part in _split_commas(inner):
            if ":" not in part:
                raise YamlError(f"invalid inline map entry: {part!r}")
            key, value = part.split(":", 1)
            out[key.strip().strip("\"'")] = _parse_scalar(value.strip())
        return out
    if re.fullmatch(r"-?[0-9]+", text):
        return int(text)
    if re.fullmatch(r"-?[0-9]+\.[0-9]+", text):
        return float(text)
    _reject_control_scalar(text)
    return text


def _reject_control_scalar(value: str) -> None:
    if CONTROL_RE.search(value):
        raise YamlError("control characters are not supported in scalar strings")


def _split_commas(text: str) -> Iterable[str]:
    parts: list[str] = []
    start = 0
    depth = 0
    quote = ""
    for i, ch in enumerate(text):
        if quote:
            if ch == quote and not _is_escaped(text, i):
                quote = ""
            continue
        if ch in ("'", '"'):
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1
