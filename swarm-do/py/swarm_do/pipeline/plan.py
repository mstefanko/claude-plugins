"""Plan parsing and inspect heuristics for plan-prepare.

Parser semantics (Tier 1+2 fixes):

- Phase titles support em-dash / en-dash / ASCII-dash / colon separators and
  trailing ``**`` from bold-wrapped headings; ``_strip_tags`` normalizes the
  edges and strips ``(complexity: ..., kind: ...)`` tags.
- ``_extract_referenced_files`` only scans inline backtick spans; tokens that
  appear inside fenced code blocks are NOT promoted to ``referenced_files``.
- ``_extract_explicit_files`` populates ``allowed_files`` only from the first
  ``### Files to create / modify`` (or ``Files Affected`` / ``File Targets``)
  section under each phase. The reader walks until the next markdown heading
  rather than a fixed line slice, so long File Targets tables are captured
  in full.
- ``_looks_like_path`` requires either a ``KNOWN_TOP_LEVEL_DIRS`` prefix or a
  recognized file extension (see ``PATH_EXTENSION_RE``); narrative slash
  tokens such as ``accept/reject`` or ``yes/no`` are rejected.
- ``inspect_phase`` no longer falls back to ``referenced_files`` when
  ``explicit_files`` is empty — phases without a Files section produce empty
  ``file_paths`` rather than leaking narrative paths into ``allowed_files``.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

from .paths import resolve_data_dir
from .run_state import utc_now


COMPLEXITIES = {"simple", "moderate", "hard", "too_large"}
DEFAULT_THRESHOLDS = {
    "simple_max_bullets": 3,
    "simple_max_files": 3,
    "moderate_max_bullets": 7,
    "cluster_ratio": 0.66,
}

PHASE_HEADING_RE = re.compile(
    r"^###\s+Phase\s+(?P<id>[A-Za-z0-9_.-]+)\s*:?\s*(?P<title>.*)$",
    re.IGNORECASE,
)
TAG_RE = re.compile(r"\((?P<body>[^)]*?\bcomplexity\s*:[^)]*?)\)", re.IGNORECASE)
KEY_VALUE_RE = re.compile(r"\b(?P<key>complexity|kind)\s*:\s*(?P<value>[A-Za-z0-9_-]+)", re.IGNORECASE)
BACKTICK_RE = re.compile(r"`([^`\n]+)`")
PATH_TOKEN_RE = re.compile(
    r"(?<![\w.-])([A-Za-z0-9_./-]+(?:\.[A-Za-z0-9]+|/[A-Za-z0-9_./-]+))(?![\w.-])"
)
FILE_SECTION_RE = re.compile(
    r"^\s{0,3}(?:#{1,6}\s*)?(?:\*\*)?(?:file targets|files affected|files to create(?:\s*/\s*modify)?|files)\b",
    re.IGNORECASE,
)
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+", re.MULTILINE)
# Anchor set for ``_looks_like_path``. A token is treated as a path only when
# its first segment is in this set (e.g. ``py/...``, ``schemas/...``) or when
# the whole token ends in a recognized extension (``PATH_EXTENSION_RE``).
# Without this guard, narrative slash tokens like ``accept/reject``,
# ``yes/no``, ``read/write`` get promoted into ``referenced_files`` and pollute
# the inspector's ``allowed_files``. To extend: add the new top-level repo
# directory name (lowercase, no leading slash) — keep this in sync with the
# real top-level entries in the repo root.
#   py            — python sources for swarm-do
#   swarm-do      — plugin tree (commands, skills, agents, role-specs, ...)
#   bin           — CLI entry points
#   docs          — long-form documentation and ADRs
#   schemas       — JSON Schemas for plan / work-unit artifacts
#   commands      — slash-command markdown
#   skills        — skill definitions
#   permissions   — permission bundles
#   role-specs    — agent role specifications
#   agents        — agent definitions
#   tests         — fixture / golden tests
#   roles         — role registry
#   rubrics       — review rubrics
#   presets       — preset configurations
#   pipelines     — pipeline definitions
#   hooks         — hook scripts
KNOWN_TOP_LEVEL_DIRS = {
    "py",
    "swarm-do",
    "bin",
    "docs",
    "schemas",
    "commands",
    "skills",
    "permissions",
    "role-specs",
    "agents",
    "tests",
    "roles",
    "rubrics",
    "presets",
    "pipelines",
    "hooks",
}
PATH_EXTENSION_RE = re.compile(
    r"\.(py|md|json|jsonl|yaml|yml|toml|sh|txt|ts|tsx|js|jsx|css|html)$"
)
ENGINE_KEYWORDS = {
    "engine",
    "pipeline",
    "dispatcher",
    "executor",
    "migration",
    "schema migration",
    "cross-module",
    "refactor engine",
}


@dataclass(frozen=True)
class ParsedPhase:
    phase_id: str
    title: str
    text: str
    complexity: str | None
    kind: str | None
    start_line: int
    end_line: int
    implementation_bullets: int
    explicit_files: list[str]
    referenced_files: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class InspectionReport:
    phase_id: str
    title: str
    complexity: str
    kind: str | None
    complexity_source: str
    estimated_files: int | None
    file_paths: list[str]
    implementation_bullets: int
    requires_decomposition: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_plan(path: str | Path) -> list[ParsedPhase]:
    """Parse a markdown plan into phase records.

    Plans without explicit ``### Phase`` headings are represented as a single
    synthetic phase covering the whole file, which keeps inspect useful for
    older scratch plans.
    """

    target = Path(path)
    text = target.read_text(encoding="utf-8")
    lines = text.splitlines()
    matches: list[tuple[int, re.Match[str]]] = []
    for idx, line in enumerate(lines):
        match = PHASE_HEADING_RE.match(line)
        if match:
            matches.append((idx, match))

    if not matches:
        return [_build_phase("plan", target.stem, lines, 0, len(lines))]

    phases: list[ParsedPhase] = []
    for offset, (line_idx, match) in enumerate(matches):
        end_idx = matches[offset + 1][0] if offset + 1 < len(matches) else len(lines)
        phase_id = match.group("id").strip().rstrip(":")
        title = _strip_tags(match.group("title").strip()) or f"Phase {phase_id}"
        phases.append(_build_phase(phase_id, title, lines, line_idx, end_idx))
    return phases


def inspect_phase(phase: ParsedPhase, thresholds: Mapping[str, Any] | None = None) -> InspectionReport:
    values = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        values.update({key: value for key, value in thresholds.items() if value is not None})

    files = _dedupe(phase.explicit_files)
    estimated_files = len(files) if files else None
    if phase.complexity in COMPLEXITIES:
        complexity = phase.complexity
        source = "explicit"
        reason = f"explicit complexity tag: {complexity}"
    else:
        complexity, reason = _infer_complexity(phase, files, values)
        source = "inferred"

    return InspectionReport(
        phase_id=phase.phase_id,
        title=phase.title,
        complexity=complexity,
        kind=phase.kind,
        complexity_source=source,
        estimated_files=estimated_files,
        file_paths=files,
        implementation_bullets=phase.implementation_bullets,
        requires_decomposition=complexity in {"moderate", "hard", "too_large"},
        reason=reason,
    )


def inspect_plan(path: str | Path, *, phase_id: str | None = None, thresholds: Mapping[str, Any] | None = None) -> list[InspectionReport]:
    phases = parse_plan(path)
    if phase_id is not None:
        phases = [phase for phase in phases if phase.phase_id == phase_id]
        if not phases:
            raise ValueError(f"phase not found: {phase_id}")
    return [inspect_phase(phase, thresholds=thresholds) for phase in phases]


def write_inspect_run(
    plan_path: str | Path,
    reports: list[InspectionReport],
    *,
    data_dir: str | Path | None = None,
    run_id: str | None = None,
    bd_epic_id: str | None = None,
) -> dict[str, Any]:
    """Persist the prepared run shell and inspect artifact."""

    target = Path(plan_path)
    base = Path(data_dir) if data_dir else resolve_data_dir()
    actual_run_id = run_id or new_run_id()
    run_dir = base / "runs" / actual_run_id
    inspect_path = run_dir / "inspect.v1.json"
    run_path = run_dir / "run.json"
    now = utc_now()
    report_payload = {
        "schema_version": 1,
        "run_id": actual_run_id,
        "plan_path": str(target),
        "plan_sha": _sha256_file(target),
        "created_at": now,
        "reports": [report.to_dict() for report in reports],
    }
    run_payload = {
        "schema_version": 1,
        "run_id": actual_run_id,
        "bd_epic_id": bd_epic_id,
        "plan_path": str(target),
        "plan_sha": report_payload["plan_sha"],
        "status": "prepared",
        "created_at": now,
        "inspect_path": str(inspect_path),
    }
    run_dir.mkdir(parents=True, exist_ok=True)
    inspect_path.write_text(json.dumps(report_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run_path.write_text(json.dumps(run_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    index_path = base / "runs" / "index.jsonl"
    with index_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(run_payload, sort_keys=True, separators=(",", ":")) + "\n")
    return {"run_id": actual_run_id, "inspect_path": str(inspect_path), "run_path": str(run_path)}


def new_run_id() -> str:
    """Return a compact ULID-shaped identifier without adding a dependency."""

    alphabet = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    timestamp_ms = int(time.time() * 1000)
    encoded = ""
    value = timestamp_ms
    for _ in range(10):
        encoded = alphabet[value % 32] + encoded
        value //= 32
    random_part = "".join(alphabet[secrets.randbelow(32)] for _ in range(16))
    return encoded + random_part


def _build_phase(phase_id: str, title: str, lines: list[str], start_idx: int, end_idx: int) -> ParsedPhase:
    body = "\n".join(lines[start_idx:end_idx]).strip()
    heading = lines[start_idx] if start_idx < len(lines) else title
    tags = _extract_tags(heading + "\n" + body[:600])
    explicit_files = _extract_explicit_files(lines[start_idx:end_idx])
    referenced_files = _extract_referenced_files(body)
    return ParsedPhase(
        phase_id=phase_id,
        title=title,
        text=body,
        complexity=tags.get("complexity"),
        kind=tags.get("kind"),
        start_line=start_idx + 1,
        end_line=end_idx,
        implementation_bullets=len(BULLET_RE.findall(body)),
        explicit_files=explicit_files,
        referenced_files=referenced_files,
    )


def _extract_tags(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for match in TAG_RE.finditer(text):
        for kv in KEY_VALUE_RE.finditer(match.group("body")):
            result[kv.group("key").lower()] = kv.group("value").lower()
    if result:
        return result
    for kv in KEY_VALUE_RE.finditer(text[:300]):
        result[kv.group("key").lower()] = kv.group("value").lower()
    return result


def _strip_tags(title: str) -> str:
    """Strip TAG_RE complexity markers and trim leading/trailing punctuation.

    Handles em-dash, en-dash, ASCII dash, colon, and bold markers (``*``)
    that surround the title body. Also collapses trailing ``*+`` runs left
    behind when ``TAG_RE`` chews the parenthesized body out of ``*(...)*``.
    """

    without_tag = TAG_RE.sub("", title)
    leading_stripped = re.sub(r"^[\s\-—–:*]+", "", without_tag)
    trailing_stripped = re.sub(r"\s*\*+\s*$", "", leading_stripped)
    trailing_stripped = re.sub(r"[\s\-—–:*]+$", "", trailing_stripped)
    return trailing_stripped.strip()


def _extract_explicit_files(lines: list[str]) -> list[str]:
    """Extract explicit file paths from File Targets / Files-affected sections.

    Reads the section body until the next markdown heading (``#``..``######``)
    instead of imposing a fixed line cap, so large File-Targets tables are
    captured in full.
    """

    paths: list[str] = []
    idx = 0
    total = len(lines)
    while idx < total:
        line = lines[idx]
        if not FILE_SECTION_RE.match(line):
            idx += 1
            continue
        cursor = idx + 1
        while cursor < total:
            candidate = lines[cursor]
            if HEADING_RE.match(candidate):
                break
            paths.extend(_paths_from_text(candidate))
            cursor += 1
        idx = cursor
    return _dedupe(paths)


def _extract_referenced_files(text: str) -> list[str]:
    """Collect path-like tokens from inline backticks only.

    Code fences are reference-only and must not contribute to file
    extraction; they routinely contain command arguments (e.g. ``rg``
    patterns) that look like paths but are not the phase's own scope.
    """

    paths: list[str] = []
    for match in BACKTICK_RE.finditer(text):
        paths.extend(_paths_from_text(match.group(1)))
    return _dedupe(paths)


def _paths_from_text(text: str) -> list[str]:
    paths: list[str] = []
    for match in PATH_TOKEN_RE.finditer(text):
        token = match.group(1).strip(".,:;()[]{}\"'")
        if _looks_like_path(token):
            paths.append(token)
    return paths


def _looks_like_path(value: str) -> bool:
    if not value or " " in value or value.startswith(("http://", "https://")):
        return False
    if value in {".", ".."} or value.startswith("-"):
        return False
    if value.startswith("/"):
        return False
    if "/" in value:
        head = value.split("/", 1)[0]
        if head in KNOWN_TOP_LEVEL_DIRS:
            return True
        return bool(PATH_EXTENSION_RE.search(value))
    return bool(PATH_EXTENSION_RE.search(value))


def _infer_complexity(phase: ParsedPhase, files: list[str], thresholds: Mapping[str, Any]) -> tuple[str, str]:
    lower = phase.text.lower()
    bullet_count = phase.implementation_bullets
    file_count = len(files)
    if _looks_too_large(phase, files):
        return "too_large", "multiple unrelated objectives or explicit too-large signal"
    if any(keyword in lower for keyword in ENGINE_KEYWORDS):
        return "hard", "engine/pipeline/migration keyword"
    if bullet_count >= 8:
        return "hard", f"{bullet_count} implementation bullets"
    if files and not _coherent_file_cluster(files, float(thresholds["cluster_ratio"])):
        return "hard", "referenced files span multiple directories"
    if file_count == 0:
        return "moderate", "no explicit file scope; classification uncertain"
    if bullet_count <= int(thresholds["simple_max_bullets"]) and file_count <= int(thresholds["simple_max_files"]):
        return "simple", f"{bullet_count} bullets and {file_count} likely files"
    if bullet_count <= int(thresholds["moderate_max_bullets"]) and _coherent_file_cluster(files, float(thresholds["cluster_ratio"])):
        return "moderate", "bounded bullets in a coherent file cluster"
    return "hard", "scope exceeds simple/moderate thresholds"


def _looks_too_large(phase: ParsedPhase, files: list[str]) -> bool:
    lower = phase.text.lower()
    if "too_large" in lower or "too large" in lower:
        return True
    headings = re.findall(r"^#{4,6}\s+\S+", phase.text, flags=re.MULTILINE)
    if len(headings) >= 6 and len(files) >= 12:
        return True
    return False


def _coherent_file_cluster(files: list[str], threshold: float) -> bool:
    if len(files) <= 1:
        return True
    dirs: dict[str, int] = {}
    for path in files:
        parent = str(Path(path).parent)
        if parent == ".":
            parent = ""
        dirs[parent] = dirs.get(parent, 0) + 1
    return max(dirs.values()) / len(files) >= threshold


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = value.strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result
