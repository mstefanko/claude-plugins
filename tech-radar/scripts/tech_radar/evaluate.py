"""Evaluate command: prepare pending repos for Claude evaluation and save verdicts."""

import json
import os

from .db import get_latest_scan_id, get_repo_by_name, save_verdict


def get_pending_repos(db, config_path="~/.tech-radar.json"):
    """Return a JSON-serializable dict of repos needing verdicts from the latest scan.

    Includes project config so Claude has stack context for evaluation.
    """
    scan_id = get_latest_scan_id(db)
    if scan_id is None:
        return {"pending_count": 0, "projects": {}, "repos": []}

    # Load project config
    config_path = os.path.expanduser(config_path)
    projects = {}
    if os.path.exists(config_path):
        with open(config_path, "r") as f:
            config = json.load(f)
        projects = config.get("projects", {})

    # Fetch pending snapshots from the latest scan joined with repo metadata
    rows = db.execute("""
        SELECT
            r.full_name,
            r.description,
            ss.stars,
            ss.stars_delta,
            ss.stars_delta_pct,
            ss.category,
            ss.matched_projects,
            ss.matched_keywords,
            ss.hn_context
        FROM scan_snapshots ss
        JOIN repos r ON r.id = ss.repo_id
        WHERE ss.scan_id = ?
          AND ss.needs_verdict = 1
        ORDER BY ss.stars DESC
    """, [scan_id]).fetchall()

    repos = []
    for row in rows:
        full_name = row[0]
        description = row[1]
        stars = row[2]
        stars_delta = row[3]
        stars_delta_pct = row[4]
        category = row[5]
        matched_projects_raw = row[6]
        matched_keywords_raw = row[7]
        hn_context = row[8]

        # Parse JSON list fields
        matched_projects = _parse_json_list(matched_projects_raw)
        matched_keywords = _parse_json_list(matched_keywords_raw)

        # Look up previous verdict
        prev = db.execute("""
            SELECT v.verdict_text
            FROM verdicts v
            JOIN repos r2 ON r2.id = v.repo_id
            WHERE r2.full_name = ?
            ORDER BY v.scan_id DESC
            LIMIT 1
        """, [full_name]).fetchone()

        is_new = prev is None
        previous_verdict = prev[0] if prev else None

        repos.append({
            "full_name": full_name,
            "description": description or "",
            "stars": stars,
            "stars_delta": stars_delta,
            "stars_delta_pct": stars_delta_pct,
            "category": category,
            "matched_projects": matched_projects,
            "matched_keywords": matched_keywords,
            "is_new": is_new,
            "hn_context": hn_context or "",
            "previous_verdict": previous_verdict,
        })

    return {
        "pending_count": len(repos),
        "projects": projects,
        "repos": repos,
    }


def save_verdicts(db, verdicts_json, scan_id=None, tokens_in=None,
                  tokens_out=None, web_searches=None):
    """Save a list of verdict dicts to the database.

    Each verdict dict must have: full_name, verdict_text, project_relevance.
    Optionally: reddit_validation.

    If scan_id is None, uses the latest scan. Updates scans.metadata with
    token tracking info if provided.
    """
    if scan_id is None:
        scan_id = get_latest_scan_id(db)
    if scan_id is None:
        raise ValueError("No scans exist in the database")

    saved = 0
    for v in verdicts_json:
        repo = get_repo_by_name(db, v["full_name"])
        if repo is None:
            print(f"Warning: repo '{v['full_name']}' not found in DB, skipping")
            continue

        verdict_data = {
            "verdict_text": v["verdict_text"],
            "project_relevance": v.get("project_relevance", ""),
            "reddit_validation": v.get("reddit_validation", ""),
        }
        save_verdict(db, repo["id"], scan_id, verdict_data)
        # Clear needs_verdict flag so this repo isn't re-evaluated
        db.execute(
            "UPDATE scan_snapshots SET needs_verdict = 0 WHERE repo_id = ? AND scan_id = ?",
            [repo["id"], scan_id]
        )
        saved += 1

    # Update scans.metadata with token tracking
    tracking = {}
    if tokens_in is not None:
        tracking["tokens_in"] = tokens_in
    if tokens_out is not None:
        tracking["tokens_out"] = tokens_out
    if web_searches is not None:
        tracking["web_searches"] = web_searches

    if tracking:
        _merge_scan_metadata(db, scan_id, tracking)

    return {"saved": saved, "scan_id": scan_id}


def save_key_takeaways(db, scan_id, takeaways_text):
    """Store key takeaways in scans.metadata JSON (merge with existing)."""
    _merge_scan_metadata(db, scan_id, {"key_takeaways": takeaways_text})


def _merge_scan_metadata(db, scan_id, new_data):
    """Merge new_data into the existing metadata JSON for a scan."""
    row = db.execute(
        "SELECT metadata FROM scans WHERE id = ?", [scan_id]
    ).fetchone()

    existing = {}
    if row and row[0]:
        try:
            existing = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            existing = {}

    existing.update(new_data)
    db.execute(
        "UPDATE scans SET metadata = ? WHERE id = ?",
        [json.dumps(existing), scan_id]
    )


def _parse_json_list(raw):
    """Parse a JSON string to a list, returning empty list on failure."""
    if not raw:
        return []
    if isinstance(raw, list):
        return raw
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except (json.JSONDecodeError, TypeError):
        return []
