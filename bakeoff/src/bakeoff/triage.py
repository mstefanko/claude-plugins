from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from bakeoff.report_index import ACTIONABLE_REPORT_SECTIONS, SKIP_REPORT_BULLETS
from bakeoff.work_order import ValidationError

FINDING_ID_RE = re.compile(r"^\s*-\s+\*\*(F-\d{3})\*\*\s+(.*)$")
TRIAGE_ACTION_RE = re.compile(
    r"\b(?:bug|bugs|fix|fixes|fixed|gap|gaps|missing|invalid|schema_error|drift)\b",
    re.IGNORECASE,
)
PRIMARY_EXPLANATION_ACTION_RE = re.compile(
    r"\b(?:bug|bugs|fix|fixes|gap|gaps|missing coverage|missing test|missing tests|"
    r"no test|no tests|untested|incorrect|mismatch|drift|risk|risks|risky|omits?|should)\b",
    re.IGNORECASE,
)
PRIMARY_EXPLANATION_DOC_DRIFT_RE = re.compile(
    r"\b(?:README|docs?|documentation)\b.*\b(?:but|omits?|missing|drift|mismatch|incorrect)\b",
    re.IGNORECASE,
)
TRIAGE_SOURCE_SECTIONS = {"Actionable Follow-ups", "Conflicts", "Unknowns"}
PATH_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/")


def build_finding_index(report_text: str) -> tuple[list[dict[str, str]], bool]:
    entries = []
    section: str | None = None
    for line in report_text.splitlines():
        if line.startswith("## "):
            section = line.removeprefix("## ").strip()
            continue
        if line.startswith("### "):
            continue
        match = FINDING_ID_RE.match(line)
        if match:
            entry = {"id": match.group(1), "text": match.group(2).strip()}
            if section:
                entry["section"] = section
            entries.append(entry)
    if entries:
        return entries, False

    section = None
    for line in report_text.splitlines():
        if line.startswith("## "):
            section = line.removeprefix("## ").strip()
            continue
        if line.startswith("### "):
            continue
        if section not in ACTIONABLE_REPORT_SECTIONS or not line.startswith("- "):
            continue
        text = line[2:].strip()
        if text not in SKIP_REPORT_BULLETS:
            entries.append({"id": f"LEGACY-F-{len(entries) + 1:03d}", "text": text, "section": section})
    return entries, bool(entries)


def select_triage_source_findings(findings: list[dict[str, str]]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return findings worth sending to triage, skipping ordinary factual report entries."""
    selected = []
    skipped = []
    for finding in findings:
        section = finding.get("section")
        text = finding.get("text", "")
        if section in TRIAGE_SOURCE_SECTIONS:
            selected.append(finding)
        elif section == "Primary Explanation":
            if PRIMARY_EXPLANATION_ACTION_RE.search(text) or PRIMARY_EXPLANATION_DOC_DRIFT_RE.search(text):
                selected.append(finding)
            else:
                skipped.append(finding)
        elif TRIAGE_ACTION_RE.search(text):
            selected.append(finding)
        else:
            skipped.append(finding)
    return selected, skipped


def compute_input_hashes(run_dir: Path) -> dict[str, str]:
    return {
        "decision_sha256": sha256_file(run_dir / "decision.json"),
        "report_sha256": sha256_file(run_dir / "report.md"),
        "work_order_sha256": sha256_file(run_dir / "work-order.json"),
    }


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError as exc:
        raise ValidationError(f"{path} is required for triage") from exc


def triage_state(run_dir: Path) -> str:
    final = read_json(run_dir / "triage" / "final.json")
    if not isinstance(final, dict) or not (run_dir / "triage" / "triage.md").exists():
        return "no"
    hashes = final.get("input_hashes")
    if not isinstance(hashes, dict):
        return "stale"
    try:
        current = compute_input_hashes(run_dir)
    except ValidationError:
        return "stale"
    if hashes.get("decision_sha256") != current["decision_sha256"] or hashes.get("report_sha256") != current["report_sha256"]:
        return "stale"
    return "yes"


def should_recommend_triage(work_order: dict[str, Any], decision: dict[str, Any], report_text: str) -> str | None:
    findings, _ = build_finding_index(report_text)
    if work_order.get("type") == "gather" and len(findings) >= 5:
        return f"gather report with {len(findings)} findings - verify before fixing"
    if decision.get("decision_kind") in {"single_provider_only", "both_failed", "tie"}:
        return f"{decision.get('decision_kind')} decision - verify before fixing"
    source_findings, _ = select_triage_source_findings(findings)
    finding_text = "\n".join(finding.get("text", "") for finding in source_findings)
    match = TRIAGE_ACTION_RE.search(finding_text)
    if match:
        return f"report mentions {match.group(0).lower()} - verify before fixing"
    if any(finding.get("section") == "Conflicts" for finding in source_findings):
        return "report contains conflicts - verify before fixing"
    return None


def resolve_citation_cwd(meta: dict[str, Any]) -> tuple[Path, list[str]]:
    caveats: list[str] = []
    cwd_value = meta.get("cwd")
    if isinstance(cwd_value, str) and cwd_value.strip():
        try:
            cwd = Path(cwd_value).expanduser().resolve(strict=True)
        except OSError:
            caveats.append("original cwd from meta.json does not exist; using current working directory for citation checks")
        else:
            if cwd.is_dir():
                return cwd, caveats
            caveats.append("original cwd from meta.json is not a directory; using current working directory for citation checks")
    else:
        caveats.append("original cwd missing from meta.json; using current working directory for citation checks")
    return Path.cwd().resolve(), caveats


def collect_citation_text(run_dir: Path, report_text: str, decision: dict[str, Any]) -> str:
    parts = [report_text, json.dumps(decision, sort_keys=True)]
    for path in sorted((run_dir / "providers").glob("*/final.json")):
        parts.append(path.read_text(encoding="utf-8", errors="replace"))
    for path in sorted((run_dir / "judge").glob("result*.json")):
        parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def extract_citations_from_text(text: str) -> list[str]:
    citations: list[str] = []
    seen: set[str] = set()
    index = 0
    while index < len(text):
        colon = text.find(":", index)
        if colon == -1:
            break
        parsed = _parse_citation_at_colon(text, colon)
        if parsed is None:
            index = colon + 1
            continue
        citation, next_index = parsed
        if citation not in seen:
            seen.add(citation)
            citations.append(citation)
        index = next_index
    return citations


def _parse_citation_at_colon(text: str, colon: int) -> tuple[str, int] | None:
    if colon + 1 >= len(text) or not text[colon + 1].isdigit():
        return None
    path_start = colon
    while path_start > 0 and text[path_start - 1] in PATH_CHARS:
        path_start -= 1
    raw_path = text[path_start:colon]
    if not _looks_like_supported_path(raw_path, text, path_start):
        return None

    line_end = colon + 1
    while line_end < len(text) and text[line_end].isdigit():
        line_end += 1
    if line_end < len(text) and text[line_end] == "-":
        range_end = line_end + 1
        while range_end < len(text) and text[range_end].isdigit():
            range_end += 1
        if range_end > line_end + 1:
            line_end = range_end
    return text[path_start:line_end], line_end


def _looks_like_supported_path(raw_path: str, full_text: str, start: int) -> bool:
    if not raw_path or raw_path.startswith("//") or "://" in raw_path:
        return False
    if "://" in full_text[max(0, start - 12) : start + len(raw_path)]:
        return False
    if raw_path.endswith(".") or "." not in Path(raw_path).name:
        return False
    return raw_path.startswith(("/", "./", "../")) or "/" in raw_path or raw_path[0].isalnum()


def check_citations(citations: list[str], cwd: Path) -> dict[str, Any]:
    checks = []
    for index, citation in enumerate(citations, start=1):
        check = check_citation(citation, cwd)
        check["id"] = f"C-{index:03d}"
        checks.append(check)
    return {"schema_version": 1, "cwd": str(cwd), "checks": checks}


def check_citation(citation: str, cwd: Path) -> dict[str, Any]:
    parsed = parse_citation(citation)
    if parsed is None:
        return {"citation": citation, "status": "unsupported"}
    raw_path, line_start, line_end = parsed
    resolved = raw_path.resolve() if raw_path.is_absolute() else (cwd / raw_path).resolve()
    base = {
        "citation": citation,
        "resolved_path": str(resolved),
        "line_start": line_start,
        "line_end": line_end,
    }
    if not is_relative_to(resolved, cwd):
        return {**base, "status": "path_escape"}
    if not resolved.exists():
        return {**base, "status": "missing_file"}
    try:
        lines = resolved.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return {**base, "status": "read_error", "error": str(exc)}
    if line_start <= 0 or line_end < line_start or line_start > len(lines) or line_end > len(lines):
        return {**base, "status": "line_out_of_range", "line_count": len(lines)}

    excerpt_start = max(1, line_start - 1)
    excerpt_end = min(len(lines), max(line_end, line_start + 1))
    while excerpt_end - excerpt_start + 1 > 3:
        excerpt_end -= 1
    excerpt = "\n".join(lines[line_number - 1] for line_number in range(excerpt_start, excerpt_end + 1))
    return {**base, "status": "ok", "excerpt": excerpt}


def parse_citation(citation: str) -> tuple[Path, int, int] | None:
    if ":" not in citation:
        return None
    raw_path, raw_lines = citation.rsplit(":", 1)
    if not raw_path or not raw_lines:
        return None
    if "-" in raw_lines:
        start_text, end_text = raw_lines.split("-", 1)
    else:
        start_text = end_text = raw_lines
    if not start_text.isdigit() or not end_text.isdigit():
        return None
    return Path(raw_path), int(start_text), int(end_text)


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def render_triage_markdown(final: dict[str, Any], caveats: list[str]) -> str:
    lines = [f"# Bakeoff Triage: {final.get('run_id')}", "", "## Summary", "", str(final.get("summary", ""))]
    source_filter = final.get("source_finding_filter")
    if isinstance(source_filter, dict):
        included = source_filter.get("included", 0)
        skipped = source_filter.get("skipped_non_actionable", 0)
        lines.extend(
            [
                "",
                "## Source Findings",
                "",
                f"- Selected: `{included}`",
                f"- Skipped non-actionable: `{skipped}`",
            ]
        )
    if caveats:
        lines.extend(["", "## Caveats"])
        lines.extend(f"- {caveat}" for caveat in caveats)
    buckets = {
        "Fix Now": [],
        "False Positives": [],
        "Needs Reproduction": [],
        "Defer / Product Decision": [],
    }
    for item in final.get("items", []):
        bucket = triage_markdown_bucket(item)
        if bucket:
            buckets[bucket].append(item)
    for title, selected in buckets.items():
        lines.extend(["", f"## {title}", ""])
        lines.extend(format_triage_item(item) for item in selected)
        if not selected:
            lines.append("- None.")
    lines.extend(["", "## Unknowns", ""])
    unknowns = final.get("unknowns") or []
    lines.extend(f"- {item}" for item in unknowns)
    if not unknowns:
        lines.append("- None.")
    return "\n".join(lines) + "\n"


def triage_markdown_bucket(item: dict[str, Any]) -> str | None:
    classification = item.get("classification")
    action = item.get("recommended_action")
    if action == "fix_now":
        return "Fix Now"
    if classification in {"false_positive", "already_fixed"}:
        return "False Positives"
    if action == "reproduce" or classification in {"needs_repro", "evidence_gap"}:
        return "Needs Reproduction"
    if action in {"document", "defer"} or classification in {"plan_doc_drift", "product_decision"}:
        return "Defer / Product Decision"
    return None


def format_triage_item(item: dict[str, Any]) -> str:
    source = " ".join(str(item.get("source_finding", item.get("source_finding_id", ""))).split())
    rationale = " ".join(str(item.get("rationale", "")).split())
    return f"- [{item.get('id')}] {source} - {rationale}"


def read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
