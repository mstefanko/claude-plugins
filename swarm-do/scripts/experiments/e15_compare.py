#!/usr/bin/env python3
"""E15 — Status grammar probe.

Compare two marker-grammar variants on synthetic fixtures and (optionally) real dispatcher transcripts:

  (a) Extended marker tokens — four status tokens emitted in dispatcher prose:
        STAGE_COMPLETE:<unit_id>:<tool_use_id>:<result_path>
        STAGE_FAILED:<unit_id>:<tool_use_id>:<failure_kind>
        STAGE_DONE_WITH_CONCERNS:<unit_id>:<tool_use_id>:<concerns>
        STAGE_NEEDS_CONTEXT:<unit_id>:<tool_use_id>:<missing_context>

  (b) Binary marker + structured artifact JSON:
        STAGE_COMPLETE:<unit_id>:<result_path>     OR
        STAGE_FAILED:<unit_id>:<failure_kind>
      AND the artifact at <result_path> contains {"status": "complete" | "done_with_concerns" | "needs_context", ...}

Measures:
  - Parse-failure modes per variant on adversarial inputs
  - Observability: variant (a) learns status at marker-emission time; variant (b) only at artifact-read time
  - Code surface (LOC) for each parser
"""
from __future__ import annotations

import json
import os
import re
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(os.environ.get("EXPERIMENT_ROOT", "/tmp/swarmdaddy-experiments")) / "e15"
ROOT.mkdir(parents=True, exist_ok=True)


# ---------- Variant (a): four-token regex ----------

VARIANT_A_TOKENS = (
    "STAGE_COMPLETE",
    "STAGE_FAILED",
    "STAGE_DONE_WITH_CONCERNS",
    "STAGE_NEEDS_CONTEXT",
)
VARIANT_A_RE = re.compile(
    r"^(?P<token>%s):(?P<unit>[^:\s]+):(?P<tool_use_id>[^:\s]+):(?P<payload>.+)$"
    % "|".join(VARIANT_A_TOKENS),
    re.MULTILINE,
)


@dataclass
class ParsedMarker:
    status: str
    unit_id: str
    tool_use_id: str
    payload: str


def parse_variant_a(stream_text: str) -> list[ParsedMarker]:
    out: list[ParsedMarker] = []
    for m in VARIANT_A_RE.finditer(stream_text):
        token = m.group("token")
        status = {
            "STAGE_COMPLETE": "complete",
            "STAGE_FAILED": "failed",
            "STAGE_DONE_WITH_CONCERNS": "done_with_concerns",
            "STAGE_NEEDS_CONTEXT": "needs_context",
        }[token]
        out.append(ParsedMarker(status, m.group("unit"), m.group("tool_use_id"), m.group("payload").strip()))
    return out


# ---------- Variant (b): binary marker + artifact JSON ----------

VARIANT_B_RE = re.compile(
    r"^(?P<token>STAGE_COMPLETE|STAGE_FAILED):(?P<unit>[^:\s]+):(?P<payload>.+)$",
    re.MULTILINE,
)


def parse_variant_b(stream_text: str, artifact_lookup) -> list[ParsedMarker]:
    """Variant (b) parses the binary marker, then dereferences the artifact for status."""
    out: list[ParsedMarker] = []
    for m in VARIANT_B_RE.finditer(stream_text):
        token = m.group("token")
        unit = m.group("unit")
        payload = m.group("payload").strip()
        if token == "STAGE_FAILED":
            out.append(ParsedMarker("failed", unit, "", payload))
            continue
        # token == STAGE_COMPLETE — dereference artifact
        artifact_path = payload
        artifact = artifact_lookup(artifact_path)
        if artifact is None:
            out.append(ParsedMarker("artifact_missing", unit, "", artifact_path))
            continue
        try:
            doc = json.loads(artifact)
        except json.JSONDecodeError:
            out.append(ParsedMarker("artifact_malformed", unit, "", artifact_path))
            continue
        status = doc.get("status", "missing_status")
        out.append(ParsedMarker(status, unit, "", artifact_path))
    return out


# ---------- Synthetic fixtures ----------

FIXTURES = {
    "clean_complete": {
        "stream": "Working...\nSTAGE_COMPLETE:u1:toolu_abc123:/tmp/wt-1/result.json\nDone.",
        "artifacts": {"/tmp/wt-1/result.json": json.dumps({"status": "complete", "summary": "ok"})},
        "expected_a": [("complete", "u1")],
        "expected_b": [("complete", "u1")],
    },
    "concerns_a_only": {
        "stream": "STAGE_DONE_WITH_CONCERNS:u2:toolu_def456:tests pass but flaky",
        "artifacts": {},
        "expected_a": [("done_with_concerns", "u2")],
        "expected_b": [],  # variant (b) doesn't have this token
    },
    "concerns_b_via_artifact": {
        "stream": "STAGE_COMPLETE:u2:/tmp/wt-2/result.json",
        "artifacts": {"/tmp/wt-2/result.json": json.dumps({"status": "done_with_concerns", "concerns": "flaky"})},
        "expected_a": [],  # variant (a) wouldn't see structured concerns
        "expected_b": [("done_with_concerns", "u2")],
    },
    "truncated_marker": {
        "stream": "STAGE_COMPLE",
        "artifacts": {},
        "expected_a": [],
        "expected_b": [],
    },
    "misspelled_token": {
        "stream": "STAGE_COMPLET:u3:toolu_xyz:/tmp/wt-3/result.json",
        "artifacts": {},
        "expected_a": [],
        "expected_b": [],
    },
    "marker_in_code_fence": {
        # adversarial: the dispatcher prose contains an example inside a fence
        "stream": "Here is the format: ```\nSTAGE_COMPLETE:fake:toolu_fake:/dev/null\n```\nSTAGE_COMPLETE:u4:toolu_real:/tmp/wt-4/result.json",
        "artifacts": {"/tmp/wt-4/result.json": json.dumps({"status": "complete"})},
        "expected_a": [("complete", "fake"), ("complete", "u4")],  # both regex variants will match — both are false-positive prone
        "expected_b": [("complete", "fake"), ("complete", "u4")],  # same — except (b) needs an artifact for fake (will be artifact_missing)
        # NB: fake's artifact is /dev/null which can be opened but is empty -> json malformed
    },
    "two_markers_one_line": {
        "stream": "STAGE_COMPLETE:u5:tu5:/tmp/r5.json STAGE_FAILED:u6:tu6:test_timeout",
        "artifacts": {"/tmp/r5.json": json.dumps({"status": "complete"})},
        "expected_a": [],  # ^ regex anchors per-line; only matches if marker is the only thing on a line
        "expected_b": [],
    },
    "missing_artifact_for_b": {
        "stream": "STAGE_COMPLETE:u7:/tmp/nope.json",
        "artifacts": {},
        "expected_a": [],  # variant (a) can't parse this — missing tool_use_id
        "expected_b": [("artifact_missing", "u7")],
    },
    "malformed_artifact_for_b": {
        "stream": "STAGE_COMPLETE:u8:/tmp/bad.json",
        "artifacts": {"/tmp/bad.json": "{not valid json"},
        "expected_a": [],
        "expected_b": [("artifact_malformed", "u8")],
    },
    "artifact_missing_status": {
        "stream": "STAGE_COMPLETE:u9:/tmp/nostatus.json",
        "artifacts": {"/tmp/nostatus.json": json.dumps({"summary": "no status field"})},
        "expected_a": [],
        "expected_b": [("missing_status", "u9")],
    },
}


def run_fixtures():
    results = []
    for name, fx in FIXTURES.items():
        artifacts_map = fx["artifacts"]
        lookup = lambda p: artifacts_map.get(p)
        a = parse_variant_a(fx["stream"])
        b = parse_variant_b(fx["stream"], lookup)
        a_obs = [(m.status, m.unit_id) for m in a]
        b_obs = [(m.status, m.unit_id) for m in b]
        a_match = a_obs == fx["expected_a"]
        b_match = b_obs == fx["expected_b"]
        results.append({
            "fixture": name,
            "variant_a_observed": a_obs,
            "variant_a_expected": fx["expected_a"],
            "variant_a_match": a_match,
            "variant_b_observed": b_obs,
            "variant_b_expected": fx["expected_b"],
            "variant_b_match": b_match,
        })
    return results


def code_surface_loc():
    """Approximate LOC for each parser (regex + dispatcher logic)."""
    a_lines = textwrap.dedent("""
        VARIANT_A_TOKENS = (...)
        VARIANT_A_RE = re.compile(...)
        def parse_variant_a(stream_text):
            for m in VARIANT_A_RE.finditer(stream_text):
                token = m.group(...)
                status = {...}[token]
                yield ParsedMarker(status, ...)
    """).strip().splitlines()
    b_lines = textwrap.dedent("""
        VARIANT_B_RE = re.compile(...)
        def parse_variant_b(stream_text, artifact_lookup):
            for m in VARIANT_B_RE.finditer(stream_text):
                token = m.group(...)
                if token == 'STAGE_FAILED': yield ParsedMarker('failed', ...)
                else:
                    art = artifact_lookup(payload)
                    if art is None: yield 'artifact_missing'
                    try: doc = json.loads(art)
                    except: yield 'artifact_malformed'
                    yield ParsedMarker(doc.get('status', 'missing_status'), ...)
    """).strip().splitlines()
    return len(a_lines), len(b_lines)


def main():
    results = run_fixtures()
    a_loc, b_loc = code_surface_loc()

    summary_path = ROOT / "summary.md"
    results_path = ROOT / "results.json"

    with open(results_path, "w") as f:
        json.dump({"fixtures": results, "loc": {"variant_a": a_loc, "variant_b": b_loc}}, f, indent=2)

    a_match = sum(1 for r in results if r["variant_a_match"])
    b_match = sum(1 for r in results if r["variant_b_match"])
    total = len(results)

    lines = [
        "# E15 — Status grammar probe",
        "",
        f"Variant (a) — extended four-token markers:  {a_match}/{total} fixture matches; ~{a_loc} LOC parser",
        f"Variant (b) — binary marker + JSON artifact: {b_match}/{total} fixture matches; ~{b_loc} LOC parser+lookup",
        "",
        "## Per-fixture results",
        "",
        "| Fixture | (a) match | (b) match | (a) observed | (b) observed |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['fixture']} | {r['variant_a_match']} | {r['variant_b_match']} | "
            f"{r['variant_a_observed']} | {r['variant_b_observed']} |"
        )
    lines.extend([
        "",
        "## Observability",
        "",
        "- Variant (a): controller learns final status at marker-emission time during stream parsing. "
        "No artifact dereference required — useful for fast retry routing on `STAGE_NEEDS_CONTEXT`.",
        "- Variant (b): controller only learns final status after sub-agent exits AND artifact is read. "
        "Stream-time only knows complete/failed binary; richer status is JSON-validated post-hoc.",
        "",
        "## Failure-mode comparison",
        "",
        "- Both variants share the false-positive risk on markers inside code fences and "
        "two-markers-on-one-line; this is regex-anchoring, not grammar-specific.",
        "- Variant (a) has 4 tokens to parse → 4× the misspelling surface (e.g., `STAGE_COMPLET`, `STAGE_DONE_WITH_CONCERN`).",
        "- Variant (b) has 2 tokens → smaller surface, but pushes the parse-failure count to "
        "JSON validation (`artifact_missing`, `artifact_malformed`, `missing_status`).",
        "",
        "## Decision feed (CB-1)",
        "",
        "- If observability matters more than code surface → variant (a) wins.",
        "- If schema-checked status is mandatory (post-hoc validation, structured `concerns` payload) → variant (b) wins.",
        "- Hybrid: variant (b) for the structured statuses + variant (a) for `STAGE_NEEDS_CONTEXT` only "
        "(stream-time signal for fast retry routing). Cost: 2 tokens vs 4, plus JSON.",
    ])

    with open(summary_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"[e15] variant_a={a_match}/{total}  variant_b={b_match}/{total}  loc_a={a_loc} loc_b={b_loc}")
    print(f"[e15] summary: {summary_path}")
    print(f"[e15] results: {results_path}")


if __name__ == "__main__":
    main()
