"""`swarm-telemetry join-outcomes` — correlate findings with post-merge actions.

Python port of the legacy join-outcomes command. Preserves:
  - Dedup key: (finding_id, maintainer_action, followup_ref) with None -> ""
  - `gh pr list --state merged --json mergeCommit,mergedAt,number,url`
    (the analysis mandated we call `gh pr list` rather than `gh api`)
  - `gh pr list --search <finding_id> --state all` for follow-up PR detection
  - ULID generator for finding_outcome_id (Crockford base32, 26 chars)
  - Hotfix correlation requires BOTH file_path AND line_start (line-range must
    participate; file-only match forbidden) — enforces the phase-9d
    anti-pattern guard.
  - Merge anchor window: ±14 days from finding_epoch to bound candidate merges.
  - Append-only JSONL writes; --dry-run emits rows on stdout without writing.
  - Telemetry dir auto-created on first write.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from swarm_do.telemetry.registry import LEDGERS, resolve_telemetry_dir

_SELF = "swarm-telemetry: join-outcomes"
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")




def _ulid() -> str:
    now_ms = int(datetime.datetime.now(datetime.timezone.utc).timestamp() * 1000)
    ts_bits = now_ms
    t_chars: List[str] = []
    for _ in range(10):
        t_chars.append(_CROCKFORD[ts_bits & 0x1F])
        ts_bits >>= 5
    t_part = "".join(reversed(t_chars))
    rand_bytes = secrets.token_bytes(10)
    rand_int = int.from_bytes(rand_bytes, "big")
    r_chars: List[str] = []
    for _ in range(16):
        r_chars.append(_CROCKFORD[rand_int & 0x1F])
        rand_int >>= 5
    r_part = "".join(reversed(r_chars))
    return t_part + r_part


def _parse_ts(s: Any) -> Optional[datetime.datetime]:
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError, TypeError):
        return None


def _git(*args: str, cwd: str, check: bool = False) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if check and result.returncode != 0:
            return ""
        return result.stdout.strip()
    except Exception as e:
        print(f"{_SELF}: git {' '.join(args)}: {e}", file=sys.stderr)
        return ""


def _hunk_ranges_for_commit(sha: str, file_path: str, repo: str) -> List[Tuple[int, int]]:
    diff_out = _git("diff", "--unified=0", f"{sha}^..{sha}", "--", file_path, cwd=repo)
    ranges: List[Tuple[int, int]] = []
    for line in diff_out.splitlines():
        m = _HUNK_RE.match(line)
        if m:
            new_start = int(m.group(3))
            new_count_s = m.group(4)
            new_count = int(new_count_s) if new_count_s is not None else 1
            if new_count == 0:
                old_start = int(m.group(1))
                old_count_s = m.group(2)
                old_count = int(old_count_s) if old_count_s is not None else 1
                ranges.append((old_start, old_start + old_count - 1))
            else:
                ranges.append((new_start, new_start + new_count - 1))
    return ranges


def _overlaps(
    hunk_start: int, hunk_end: int, find_start: int, find_end: int, window: int = 10
) -> bool:
    lo = find_start - window
    hi = find_end + window
    return hunk_start <= hi and hunk_end >= lo


def run(args: argparse.Namespace) -> int:
    since_days = args.since or "30d"
    repo_path: Optional[str] = args.repo
    dry_run: bool = bool(args.dry_run)

    if repo_path is None:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                print(
                    f"{_SELF}: --repo not provided and not inside a git repo",
                    file=sys.stderr,
                )
                return 1
            repo_path = result.stdout.strip()
        except Exception as e:
            print(f"{_SELF}: git rev-parse failed: {e}", file=sys.stderr)
            return 1

    repo = Path(repo_path)
    if not ((repo / ".git").is_dir() or (repo / ".git").is_file()):
        print(f"{_SELF}: '{repo_path}' is not a git repository root", file=sys.stderr)
        return 1

    tel_dir = resolve_telemetry_dir()
    findings_path = tel_dir / "findings.jsonl"
    ledger_path = tel_dir / "finding_outcomes.jsonl"

    if not findings_path.is_file() or findings_path.stat().st_size == 0:
        print(
            f"swarm-telemetry: join-outcomes: findings.jsonl absent or empty — nothing to correlate",
            file=sys.stderr,
        )
        return 0

    n_str = since_days.rstrip("d").strip()
    if not n_str.isdigit():
        print(
            f"{_SELF}: --since must be Nd (e.g. 30d), got '{since_days}'",
            file=sys.stderr,
        )
        return 1
    since_n = int(n_str)

    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=since_n)
    observed_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # --------------------------------------------------------------
    # Dedup scan of existing finding_outcomes.jsonl
    # --------------------------------------------------------------
    existing_keys: set = set()
    if ledger_path.is_file() and ledger_path.stat().st_size > 0:
        with ledger_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    key = (
                        obj.get("finding_id", ""),
                        obj.get("maintainer_action", ""),
                        obj.get("followup_ref") or "",
                    )
                    existing_keys.add(key)
                except json.JSONDecodeError:
                    pass

    def is_dup(fid: str, action: str, ref: Optional[str]) -> bool:
        return (fid, action, ref or "") in existing_keys

    def mark_seen(fid: str, action: str, ref: Optional[str]) -> None:
        existing_keys.add((fid, action, ref or ""))

    # --------------------------------------------------------------
    # Load findings
    # --------------------------------------------------------------
    findings: List[Dict[str, Any]] = []
    with findings_path.open("r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                findings.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(
                    f"{_SELF}: findings.jsonl line {lineno} parse error: {e} — skipping",
                    file=sys.stderr,
                )

    if not findings:
        print(f"{_SELF}: no findings loaded — nothing to correlate", file=sys.stderr)
        return 0

    # --------------------------------------------------------------
    # Discover merges (git log --merges + gh pr list)
    # --------------------------------------------------------------
    since_epoch = int(cutoff.timestamp())
    merge_log = _git(
        "log",
        "--merges",
        f"--after={since_epoch}",
        "--format=%H %ct",
        "--no-walk=unsorted",
        cwd=str(repo),
    )
    all_commit_log = _git(
        "log",
        f"--after={since_epoch}",
        "--format=%H %ct",
        cwd=str(repo),
    )
    all_commits: List[Tuple[str, int]] = []
    for line in all_commit_log.splitlines():
        parts = line.split()
        if len(parts) == 2:
            sha, ct = parts
            try:
                all_commits.append((sha, int(ct)))
            except ValueError:
                pass

    gh_merges: Dict[str, int] = {}
    gh_available = False
    try:
        gh_result = subprocess.run(
            [
                "gh", "pr", "list", "--state", "merged", "--limit", "200",
                "--json", "mergeCommit,mergedAt,number,url",
            ],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if gh_result.returncode == 0:
            gh_available = True
            prs = json.loads(gh_result.stdout or "[]")
            for pr in prs:
                mc = pr.get("mergeCommit") or {}
                sha = mc.get("oid", "")
                merged_at = pr.get("mergedAt", "")
                if sha and merged_at:
                    ts = _parse_ts(merged_at)
                    if ts:
                        gh_merges[sha] = int(ts.timestamp())
    except Exception as e:
        print(f"{_SELF}: gh pr list failed (non-fatal): {e}", file=sys.stderr)

    merge_candidates: Dict[str, int] = {}
    for line in merge_log.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        sha, ct = parts
        try:
            merge_candidates[sha] = int(ct)
        except ValueError:
            continue
    for sha, merge_epoch in gh_merges.items():
        merge_candidates[sha] = merge_epoch
    sorted_merge_candidates = sorted(merge_candidates.items(), key=lambda item: item[1])

    def merge_anchor_for_finding(
        file_path: str, ls: int, le: int, find_epoch: int
    ) -> Optional[Tuple[str, int]]:
        candidates: List[Tuple[str, int]] = []
        max_anchor_delta = 14 * 86400
        for sha, merge_epoch in sorted_merge_candidates:
            if merge_epoch is None:
                continue
            if abs(merge_epoch - find_epoch) > max_anchor_delta:
                continue
            ranges = _hunk_ranges_for_commit(sha, file_path, str(repo))
            if any(_overlaps(h_s, h_e, ls, le) for h_s, h_e in ranges):
                candidates.append((sha, merge_epoch))
        if not candidates:
            return None
        after = [c for c in candidates if c[1] >= find_epoch]
        if after:
            return min(after, key=lambda c: (c[1] - find_epoch, c[1]))
        before = [c for c in candidates if c[1] < find_epoch]
        if before:
            return min(before, key=lambda c: (find_epoch - c[1], -c[1]))
        return None

    # bd availability check
    bd_available = False
    try:
        bd_chk = subprocess.run(
            ["bd", "--version"], capture_output=True, text=True, timeout=10
        )
        bd_available = bd_chk.returncode == 0
    except Exception:
        pass

    def bd_find_followup(fid: str) -> List[str]:
        if not bd_available:
            return []
        try:
            result = subprocess.run(
                ["bd", "list", "--notes", fid],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return []
            refs: List[str] = []
            for line in result.stdout.splitlines():
                line = line.strip()
                if line and fid in line:
                    parts = line.split()
                    if parts:
                        refs.append(parts[0])
            return refs
        except Exception:
            return []

    def gh_find_followup_prs(fid: str) -> List[str]:
        if not gh_available:
            return []
        try:
            result = subprocess.run(
                [
                    "gh", "pr", "list", "--search", fid, "--state", "all",
                    "--limit", "50", "--json", "number,url",
                ],
                cwd=str(repo),
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                return []
            prs = json.loads(result.stdout or "[]")
            return [str(pr["number"]) for pr in prs if "number" in pr]
        except Exception:
            return []

    # --------------------------------------------------------------
    # Correlate
    # --------------------------------------------------------------
    new_rows: List[Dict[str, Any]] = []

    for finding in findings:
        finding_id = finding.get("finding_id", "")
        file_path = finding.get("file_path") or ""
        line_start = finding.get("line_start")
        line_end = finding.get("line_end")
        find_ts_str = finding.get("timestamp", "")
        find_ts = _parse_ts(find_ts_str)

        if not finding_id:
            continue
        if find_ts and find_ts < cutoff:
            continue

        bd_refs = bd_find_followup(finding_id)
        for bd_ref in bd_refs:
            action = "followup_issue"
            if not is_dup(finding_id, action, bd_ref):
                new_rows.append({
                    "finding_outcome_id": _ulid(),
                    "finding_id": finding_id,
                    "observed_at": observed_at,
                    "maintainer_action": action,
                    "followup_ref": bd_ref,
                    "time_to_action_hours": None,
                    "time_to_fix_hours": None,
                    "recurrence_of": None,
                    "schema_ok": True,
                })
                mark_seen(finding_id, action, bd_ref)

        gh_pr_refs = gh_find_followup_prs(finding_id)
        for pr_num in gh_pr_refs:
            action = "followup_pr"
            if not is_dup(finding_id, action, pr_num):
                new_rows.append({
                    "finding_outcome_id": _ulid(),
                    "finding_id": finding_id,
                    "observed_at": observed_at,
                    "maintainer_action": action,
                    "followup_ref": pr_num,
                    "time_to_action_hours": None,
                    "time_to_fix_hours": None,
                    "recurrence_of": None,
                    "schema_ok": True,
                })
                mark_seen(finding_id, action, pr_num)

        if not file_path or line_start is None:
            if not bd_refs and not gh_pr_refs and not file_path:
                action = "ignored"
                if not is_dup(finding_id, action, ""):
                    new_rows.append({
                        "finding_outcome_id": _ulid(),
                        "finding_id": finding_id,
                        "observed_at": observed_at,
                        "maintainer_action": action,
                        "followup_ref": None,
                        "time_to_action_hours": None,
                        "time_to_fix_hours": None,
                        "recurrence_of": None,
                        "schema_ok": True,
                    })
                    mark_seen(finding_id, action, "")
            continue

        ls = int(line_start)
        le = int(line_end) if line_end is not None else ls

        find_epoch = int(find_ts.timestamp()) if find_ts else int(now.timestamp())
        merge_anchor = merge_anchor_for_finding(file_path, ls, le, find_epoch)
        if merge_anchor is None:
            continue
        merge_sha, merge_epoch = merge_anchor

        hotfix_commits_raw = _git(
            "log",
            f"--after={merge_epoch}",
            f"--before={merge_epoch + 14 * 86400}",
            "--format=%H %ct",
            "--",
            file_path,
            cwd=str(repo),
        )
        for cline in hotfix_commits_raw.splitlines():
            parts = cline.split()
            if len(parts) < 2:
                continue
            sha, commit_ct_s = parts[0], parts[1]
            try:
                commit_ct = int(commit_ct_s)
            except ValueError:
                continue
            if sha == merge_sha or commit_ct <= merge_epoch:
                continue
            ranges = _hunk_ranges_for_commit(sha, file_path, str(repo))
            if not ranges:
                continue
            hit = any(_overlaps(h_s, h_e, ls, le) for h_s, h_e in ranges)
            if not hit:
                continue

            action = "hotfix_within_14d"
            followup_ref = sha
            if not is_dup(finding_id, action, followup_ref):
                time_to_fix = (commit_ct - merge_epoch) / 3600.0
                new_rows.append({
                    "finding_outcome_id": _ulid(),
                    "finding_id": finding_id,
                    "observed_at": observed_at,
                    "maintainer_action": action,
                    "followup_ref": followup_ref,
                    "time_to_action_hours": None,
                    "time_to_fix_hours": round(time_to_fix, 4) if time_to_fix is not None else None,
                    "recurrence_of": None,
                    "schema_ok": True,
                })
                mark_seen(finding_id, action, followup_ref)

    if not new_rows:
        print(f"{_SELF}: no new outcome rows to append", file=sys.stderr)
        return 0

    if dry_run:
        print(
            f"{_SELF}: --dry-run: {len(new_rows)} row(s) would be appended (not written)",
            file=sys.stderr,
        )
        for row in new_rows:
            print(json.dumps(row))
        return 0

    os.makedirs(os.path.dirname(str(ledger_path)), exist_ok=True)
    appended = 0
    with ledger_path.open("a", encoding="utf-8") as f:
        for row in new_rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
            appended += 1
    print(f"{_SELF}: appended {appended} row(s) to {ledger_path}", file=sys.stderr)
    return 0
