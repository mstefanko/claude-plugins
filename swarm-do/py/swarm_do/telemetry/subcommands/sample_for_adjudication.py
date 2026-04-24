"""`swarm-telemetry sample-for-adjudication` — stratified random sample.

Byte-parity port of swarm-telemetry.legacy:720-1026. Preserves:
  - role_subdir_map (claude vs codex-mode-a routing)
  - finding_slug = finding_id.lower()[:12] directory layout
  - Proportional allocation with floor-1 per non-empty stratum
  - Env vars: SWARM_PHASE0_ROOT, CLAUDE_PLUGIN_DATA, SWARM_TELEMETRY_NOW
  - Preferred output root -> ~/.swarm/phase0/runs (or SWARM_PHASE0_ROOT)
    with fallback to <plugin-data>/phase0/runs on PermissionError
  - Adjudication exclusion: union of finding_id and overridden_finding_ids
    across adjudications.jsonl
  - Rubric version parsed from highest v*.md YAML frontmatter

Stdout is deterministic given the fixture and SWARM_TELEMETRY_NOW — only
3 summary lines are printed; sampled file tree lives under output_root.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import random
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from swarm_do.telemetry.registry import LEDGERS, PLUGIN_ROOT

_SELF = "swarm-telemetry: sample-for-adjudication"

_ROLE_SUBDIR_MAP: Dict[str, str] = {
    "agent-review": "claude",
    "agent-writer": "claude",
    "agent-research": "claude",
    "agent-clarify": "claude",
    "agent-analysis": "claude",
    "agent-spec-review": "claude",
    "agent-code-review": "claude",
    "agent-codex-review": "codex-mode-a",
    "agent-code-synthesizer": "codex-mode-a",
    "agent-docs": "codex-mode-a",
    "agent-debug": "codex-mode-a",
}


def _resolve_telemetry_dir() -> Path:
    base = os.environ.get("CLAUDE_PLUGIN_DATA")
    if base:
        return Path(base) / "telemetry"
    return PLUGIN_ROOT / "data" / "telemetry"


def _resolve_phase0_root() -> str:
    explicit = os.environ.get("SWARM_PHASE0_ROOT")
    if explicit:
        return explicit
    return os.path.expanduser("~/.swarm/phase0/runs")


def _resolve_phase0_fallback_root() -> str:
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or os.path.expanduser(
        "~/.claude/plugin-data/mstefanko-plugins/swarm-do"
    )
    return os.path.join(base, "phase0", "runs")


def _parse_ts(s: Any) -> Optional[datetime.datetime]:
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None


def _resolve_now() -> datetime.datetime:
    override = (os.environ.get("SWARM_TELEMETRY_NOW") or "").strip()
    if not override:
        return datetime.datetime.now(datetime.timezone.utc)
    parsed = _parse_ts(override)
    if parsed is None:
        print(f"{_SELF}: invalid SWARM_TELEMETRY_NOW '{override}'", file=sys.stderr)
        sys.exit(1)
    return parsed


def _find_rubric_version() -> Tuple[Path, str]:
    rubric_dir = PLUGIN_ROOT / "swarm-do" / "rubrics"
    if not rubric_dir.is_dir():
        print(
            f"{_SELF}: rubrics directory not found at {rubric_dir}", file=sys.stderr
        )
        sys.exit(1)

    candidates = sorted(
        [p for p in rubric_dir.glob("v*.md") if p.is_file()],
        key=lambda p: [int(n) for n in re.findall(r"\d+", p.stem)] or [0],
    )
    if not candidates:
        print(f"{_SELF}: no rubric v*.md found in {rubric_dir}", file=sys.stderr)
        sys.exit(1)
    highest = candidates[-1]

    version: Optional[str] = None
    with highest.open("r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("rubric_version:"):
                m = re.search(r'"([^"]*)"', line)
                if m:
                    version = m.group(1)
                break
    if not version:
        print(
            f"{_SELF}: could not parse rubric_version from {highest.name}",
            file=sys.stderr,
        )
        sys.exit(1)
    return highest, version


def run(args: argparse.Namespace) -> int:
    count_target = args.count
    since_days = args.since or ""
    output_root_arg = args.output_root

    if count_target is None:
        print(f"{_SELF}: --count is required", file=sys.stderr)
        return 1
    try:
        count_target = int(count_target)
        if count_target <= 0:
            raise ValueError
    except (TypeError, ValueError):
        print(
            f"{_SELF}: --count must be a positive integer, got '{args.count}'",
            file=sys.stderr,
        )
        return 1

    since_n = 0
    if since_days:
        n_str = since_days.rstrip("d").strip()
        if not n_str.isdigit():
            print(
                f"{_SELF}: --since must be Nd (e.g. 30d), got '{since_days}'",
                file=sys.stderr,
            )
            return 1
        since_n = int(n_str)

    tel_dir = _resolve_telemetry_dir()
    findings_path = tel_dir / "findings.jsonl"
    runs_path = tel_dir / "runs.jsonl"
    adjudications_path = tel_dir / "adjudications.jsonl"

    if not findings_path.is_file() or findings_path.stat().st_size == 0:
        print(
            f"{_SELF}: findings.jsonl absent or empty at {findings_path}",
            file=sys.stderr,
        )
        return 1
    if not runs_path.is_file() or runs_path.stat().st_size == 0:
        print(
            f"{_SELF}: runs.jsonl absent or empty at {runs_path}",
            file=sys.stderr,
        )
        return 1

    _, rubric_version = _find_rubric_version()

    preferred_output_root = output_root_arg or _resolve_phase0_root()
    fallback_output_root = _resolve_phase0_fallback_root()

    # ------------------------------------------------------------------
    # Load runs
    # ------------------------------------------------------------------
    runs_by_id: Dict[str, Dict[str, Any]] = {}
    try:
        with runs_path.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    runs_by_id[obj.get("run_id")] = obj
                except json.JSONDecodeError as e:
                    print(
                        f"{_SELF}: runs.jsonl line {lineno} parse error: {e} — skipping",
                        file=sys.stderr,
                    )
    except Exception as e:
        print(f"{_SELF}: error reading runs.jsonl: {e}", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # Load adjudications (exclusion set)
    # ------------------------------------------------------------------
    adjudicated_finding_ids: set = set()
    if adjudications_path.is_file() and adjudications_path.stat().st_size > 0:
        try:
            with adjudications_path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        overridden = obj.get("overridden_finding_ids")
                        if isinstance(overridden, list):
                            for fid in overridden:
                                if isinstance(fid, str):
                                    adjudicated_finding_ids.add(fid)
                        direct = obj.get("finding_id")
                        if isinstance(direct, str):
                            adjudicated_finding_ids.add(direct)
                    except json.JSONDecodeError:
                        pass
        except Exception as e:
            print(f"{_SELF}: error reading adjudications.jsonl: {e}", file=sys.stderr)

    now = _resolve_now()
    cutoff: Optional[datetime.datetime] = None
    if since_n > 0:
        cutoff = now - datetime.timedelta(days=since_n)

    # ------------------------------------------------------------------
    # Load findings + stratify
    # ------------------------------------------------------------------
    strata: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    try:
        with findings_path.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if cutoff:
                        ts = _parse_ts(obj.get("timestamp"))
                        if ts and ts < cutoff:
                            continue
                    finding_id = obj.get("finding_id")
                    if isinstance(finding_id, str) and finding_id in adjudicated_finding_ids:
                        continue
                    run_id = obj.get("run_id")
                    run = runs_by_id.get(run_id, {})
                    role = run.get("role", "unknown")
                    phase_complexity = run.get("phase_complexity", "unknown")
                    phase_kind = run.get("phase_kind", "unknown")
                    strata[(role, phase_complexity, phase_kind)].append(obj)
                except json.JSONDecodeError as e:
                    print(
                        f"{_SELF}: findings.jsonl line {lineno} parse error: {e} — skipping",
                        file=sys.stderr,
                    )
    except Exception as e:
        print(f"{_SELF}: error reading findings.jsonl: {e}", file=sys.stderr)
        return 1

    if not strata:
        print(f"{_SELF}: no findings matched filter criteria", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # Proportional allocation with floor-1
    # ------------------------------------------------------------------
    stratum_counts = {k: len(v) for k, v in strata.items()}
    total_findings = sum(stratum_counts.values())

    allocation: Dict[Tuple[str, str, str], int] = {}
    allocated_total = 0
    for stratum_key in strata.keys():
        proportion = stratum_counts[stratum_key] / total_findings
        base_alloc = int(proportion * count_target)
        alloc = max(1, base_alloc)
        allocation[stratum_key] = alloc
        allocated_total += alloc

    if allocated_total > count_target:
        overage = allocated_total - count_target
        sorted_strata = sorted(allocation.items(), key=lambda x: -x[1])
        for stratum_key, _ in sorted_strata:
            if overage <= 0:
                break
            trim = min(overage, allocation[stratum_key] - 1)
            allocation[stratum_key] -= trim
            overage -= trim

    # ------------------------------------------------------------------
    # Output tree + sampling
    # ------------------------------------------------------------------
    batch_id = now.strftime("%Y%m%d%H%M%S")
    date_dir = now.strftime("%Y-%m-%d")
    preferred_base_output_dir = os.path.abspath(os.path.expanduser(preferred_output_root))
    fallback_base_output_dir = os.path.abspath(os.path.expanduser(fallback_output_root))
    output_root = os.path.join(preferred_base_output_dir, date_dir)

    try:
        os.makedirs(output_root, exist_ok=True)
    except PermissionError:
        fallback_output = os.path.join(fallback_base_output_dir, date_dir)
        if os.path.abspath(fallback_output) == os.path.abspath(output_root):
            raise
        print(
            f"{_SELF}: preferred output root '{preferred_base_output_dir}' is not writable; "
            f"falling back to '{fallback_base_output_dir}'",
            file=sys.stderr,
        )
        os.makedirs(fallback_output, exist_ok=True)
        output_root = fallback_output

    sampled: List[Tuple[Tuple[str, str, str], Dict[str, Any]]] = []
    for stratum_key, target_count in allocation.items():
        findings_in_stratum = strata[stratum_key]
        sample_count = min(target_count, len(findings_in_stratum))
        sampled_findings = random.sample(findings_in_stratum, sample_count)
        for finding in sampled_findings:
            sampled.append((stratum_key, finding))

    random.shuffle(sampled)

    for stratum_key, finding in sampled:
        role = stratum_key[0]
        finding_id = finding.get("finding_id", "unknown")
        finding_slug = finding_id.lower()[:12]
        phase_dir = os.path.join(output_root, finding_slug)
        os.makedirs(phase_dir, exist_ok=True)

        role_subdir = _ROLE_SUBDIR_MAP.get(role, "claude")
        findings_subdir = os.path.join(phase_dir, role_subdir)
        os.makedirs(findings_subdir, exist_ok=True)

        findings_json_path = os.path.join(findings_subdir, "findings.json")
        with open(findings_json_path, "w") as f:
            json.dump([finding], f, indent=2)

    print(f"{_SELF}: sampled {len(sampled)} findings into {output_root}")
    print(f"{_SELF}: rubric version: {rubric_version}")
    print(f"{_SELF}: batch_id: {batch_id}")
    return 0
