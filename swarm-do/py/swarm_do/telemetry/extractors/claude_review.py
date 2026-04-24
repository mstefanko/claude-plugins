"""Claude-reviewer findings extractor — closes 9b-claude (mstefanko-plugins-7q9).

Parses `agent-review` and `agent-code-review` notes markdown (the format
documented in `swarm-do/roles/agent-review/shared.md` and
`swarm-do/agents/agent-code-review.md`) and emits one findings.v2 row per
flagged item.

Supported sections (plan ref WS-3):

  | Section            | Per-item pattern                         | severity | category         |
  |--------------------|------------------------------------------|----------|------------------|
  | ### Issues Found   | `N. <file:line> — <desc>`                | high     | correctness      |
  | ### Critical Issues| `N. [CRITICAL] <file:line> — <desc>`     | critical | correctness/security* |
  | ### Warnings       | `N. [WARNING] <file:line> — <desc>`      | medium   | tbd              |
  | ### Info           | `N. [INFO] <file:line> — <observation>`  | info     | observation      |

* category for Critical items is inferred from desc keywords:
  security / auth / injection / traversal / xss / csrf / sql -> "security",
  else -> "correctness".

Item delimiter: Markdown ordered-list line (`1.`, `2.`, ...). The text to
the right of the em-dash (`—`) or regular hyphen (` - ` / ` -- `) is the
description. `file:line` prefix is mandatory; items without a file:line
anchor are skipped (no stable_finding_hash_v1 is computable otherwise).

stable_finding_hash_v1 shares inputs with the codex extractor so equivalent
findings deduplicate cleanly in Phase 9e's cluster indexer.
"""

from __future__ import annotations

import datetime
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

from swarm_do.telemetry.ids import new_ulid

from .hashing import stable_finding_hash_v1
from .paths import normalize_path


# ---------------------------------------------------------------------------
# Section header table — ordered so longer headers beat shorter ones when
# scanning. Each entry maps the canonical header to the default severity
# and category.
# ---------------------------------------------------------------------------

_SECTION_MAP: List[Tuple[str, str, Optional[str]]] = [
    ("Critical Issues", "critical", None),  # category inferred
    ("Issues Found", "high", "correctness"),
    ("Warnings", "medium", "tbd"),
    ("Info", "info", "observation"),
]

# ---------------------------------------------------------------------------
# Item parsing.
#
# Ordered-list items look like:
#   1. [CRITICAL] internal/api/foo.go:42 — SQL injection via unvalidated param
#   2. pkg/parse/token.go:100-120 - missing nil check
#
# Leading number + period + optional bracketed severity tag is stripped, then
# we split on em-dash (preferred) or " - " / " -- " to separate the anchor
# from the description.
# ---------------------------------------------------------------------------

_ITEM_PREFIX_RE = re.compile(
    r"""^\s*
        (?:\d+\.\s+)                     # ordered-list marker
        (?:\[(?:CRITICAL|WARNING|INFO)\]\s+)?   # optional severity tag
        (.+)                             # body (anchor + description)
        $""",
    re.VERBOSE,
)

# Split body into (anchor, description). Em-dash preferred; fallback to
# dash patterns with surrounding whitespace so we don't accidentally split
# on hyphenated filenames or ranges like foo-bar.go:10-20.
_BODY_SPLIT_RE = re.compile(r"\s+(?:—|–|--|-)\s+")

# Anchor format: `file:line` or `file:line_start-line_end`. File path can
# contain dots, slashes, hyphens, underscores. Line range must be numeric.
_ANCHOR_RE = re.compile(
    r"""^\s*(?P<file>[^\s:][^\s]*?)      # file path (no whitespace)
        :(?P<line_start>\d+)             # :line_start (required)
        (?:-(?P<line_end>\d+))?          # optional -line_end
        \s*$""",
    re.VERBOSE,
)

# Category inference for Critical items. Keywords match anywhere in the
# lowercased description. Order doesn't matter; any hit routes to "security".
_SECURITY_KEYWORDS = (
    "security",
    "auth",
    "injection",
    "traversal",
    "xss",
    "csrf",
    "sql injection",
    "sqli",
    "credential",
    "secret",
    "token leak",
    "unvalidated",
)


def _infer_category(description: str, default: Optional[str]) -> str:
    if default is not None:
        return default
    lowered = description.lower()
    if any(kw in lowered for kw in _SECURITY_KEYWORDS):
        return "security"
    return "correctness"


def _iter_sections(text: str) -> List[Tuple[str, str]]:
    """Yield (header_title, body) for each `### <title>` section.

    Body excludes the header line itself; captures until the next `###` or
    `##` header (whichever comes first) or end of document.
    """
    results: List[Tuple[str, str]] = []
    # Split on lines that START a new header (### or ##). Keep delimiters.
    lines = text.splitlines()
    current_title: Optional[str] = None
    current_body: List[str] = []

    def flush() -> None:
        if current_title is not None:
            results.append((current_title, "\n".join(current_body)))

    for line in lines:
        m = re.match(r"^\s*###\s+(.+?)\s*$", line)
        if m:
            flush()
            current_title = m.group(1)
            current_body = []
            continue
        # A top-level ## (not ###) ends the current ### section as well.
        if re.match(r"^\s*##\s+(?!#)", line) and current_title is not None:
            flush()
            current_title = None
            current_body = []
            continue
        if current_title is not None:
            current_body.append(line)
    flush()
    return results


def _extract_items(body: str) -> List[str]:
    """Return raw item body strings (after the ordered-list marker and tag)."""
    items: List[str] = []
    for line in body.splitlines():
        m = _ITEM_PREFIX_RE.match(line)
        if not m:
            continue
        items.append(m.group(1).strip())
    return items


def _parse_anchor_and_description(
    item_body: str,
) -> Tuple[Optional[str], Optional[int], Optional[int], str]:
    """Split "anchor — description" into (file, start, end, description).

    Returns (None, None, None, description) when the anchor fails to parse,
    which causes the caller to skip the item (no file:line = no stable hash).
    """
    # Find first em-dash / hyphen separator. If none, the whole line is the
    # anchor with no description.
    split = _BODY_SPLIT_RE.split(item_body, maxsplit=1)
    if len(split) == 2:
        anchor_raw, description = split[0], split[1]
    else:
        anchor_raw, description = split[0], ""

    m = _ANCHOR_RE.match(anchor_raw)
    if not m:
        return (None, None, None, description.strip())
    file_raw = m.group("file")
    line_start = int(m.group("line_start"))
    line_end_str = m.group("line_end")
    line_end = int(line_end_str) if line_end_str is not None else line_start
    return (file_raw, line_start, line_end, description.strip())


def _iso_utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_row(
    file_raw: Optional[str],
    line_start: Optional[int],
    line_end: Optional[int],
    description: str,
    severity: str,
    category: str,
    run_id: str,
    role: str,
    issue_id: str,
    timestamp: str,
) -> Optional[Dict[str, Any]]:
    if not file_raw or line_start is None:
        return None

    try:
        file_path = normalize_path(file_raw)
    except Exception as exc:  # noqa: BLE001 — fail-open
        print(
            f"extract-phase: normalize_path failed for {file_raw!r}: {exc}",
            file=sys.stderr,
        )
        file_path = file_raw

    summary = description
    short_summary = description[:200]

    hash_v1 = stable_finding_hash_v1(file_path, category, line_start, short_summary)

    schema_ok = all(
        [run_id, timestamp, role, issue_id, severity, category, summary, short_summary, hash_v1]
    )

    return {
        "finding_id": new_ulid(),
        "run_id": run_id,
        "timestamp": timestamp,
        "role": role,
        "issue_id": issue_id,
        "severity": severity,
        "category": category,
        "summary": summary,
        "short_summary": short_summary,
        "file_path": file_path,
        "line_start": line_start,
        "line_end": line_end,
        "schema_ok": bool(schema_ok),
        "stable_finding_hash_v1": hash_v1,
        "duplicate_cluster_id": None,
    }


def extract(
    notes_path: str,
    run_id: str,
    role: str,
    issue_id: str,
) -> List[Dict[str, Any]]:
    """Parse agent-review / agent-code-review notes into findings.v2 rows.

    Fail-open: returns [] on any I/O error after logging to stderr. Items
    that fail to parse individually are skipped with a stderr warning.
    """
    try:
        with open(notes_path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        print(f"extract-phase: cannot read {notes_path}: {exc}", file=sys.stderr)
        return []

    timestamp = _iso_utc_now()
    rows: List[Dict[str, Any]] = []
    sections = _iter_sections(text)

    for header, body in sections:
        matched = None
        for canonical, severity, default_category in _SECTION_MAP:
            if header.strip() == canonical:
                matched = (severity, default_category)
                break
        if matched is None:
            continue
        severity, default_category = matched

        for item_body in _extract_items(body):
            try:
                file_raw, line_start, line_end, description = _parse_anchor_and_description(
                    item_body
                )
            except Exception as exc:  # noqa: BLE001 — fail-open
                print(
                    f"extract-phase: skipping malformed item {item_body!r}: {exc}",
                    file=sys.stderr,
                )
                continue

            if not file_raw or line_start is None:
                print(
                    f"extract-phase: item missing file:line anchor — skipping: {item_body!r}",
                    file=sys.stderr,
                )
                continue

            category = _infer_category(description, default_category)
            row = _build_row(
                file_raw,
                line_start,
                line_end,
                description,
                severity,
                category,
                run_id,
                role,
                issue_id,
                timestamp,
            )
            if row is not None:
                rows.append(row)

    return rows
