"""Evaluate command: prepare pending repos for Claude evaluation and save verdicts."""

import json
import os

from .db import get_latest_scan_id, get_repo_by_name, save_verdict, save_annotation


def get_pending_repos(db, config_path="~/.tech-radar.json"):
    """Return a JSON-serializable dict of repos needing verdicts from the latest scan.

    Includes project config so Claude has stack context for evaluation.
    Single query fetches all data including previous verdicts (#2: no N+1).
    """
    scan_id = get_latest_scan_id(db)
    if scan_id is None:
        return {"pending_count": 0, "projects": {}, "repos": []}

    # Load project config
    config_path = os.path.expanduser(config_path)
    projects = {}
    verticals = {}
    if os.path.exists(config_path):
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        projects = config.get("projects", {})
        verticals = config.get("verticals", {})

    # Single query: pending snapshots + repo metadata + previous verdict (#2)
    rows = db.execute("""
        SELECT
            r.full_name, r.description,
            ss.stars, ss.stars_delta, ss.stars_delta_pct,
            ss.category, ss.matched_projects, ss.matched_keywords, ss.hn_context,
            prev_v.verdict_text as previous_verdict
        FROM scan_snapshots ss
        JOIN repos r ON r.id = ss.repo_id
        LEFT JOIN verdicts prev_v ON prev_v.repo_id = ss.repo_id
            AND prev_v.scan_id = (
                SELECT MAX(v2.scan_id) FROM verdicts v2
                WHERE v2.repo_id = ss.repo_id AND v2.scan_id < ss.scan_id
            )
        WHERE ss.scan_id = ?
          AND ss.needs_verdict = 1
        ORDER BY ss.stars DESC
    """, [scan_id]).fetchall()

    repos = []
    for row in rows:
        repos.append({
            "full_name": row[0],
            "description": row[1] or "",
            "stars": row[2],
            "stars_delta": row[3],
            "stars_delta_pct": row[4],
            "category": row[5],
            "matched_projects": _parse_json_list(row[6]),
            "matched_keywords": _parse_json_list(row[7]),
            "is_new": row[9] is None,
            "hn_context": row[8] or "",
            "previous_verdict": row[9],
        })

    return {
        "pending_count": len(repos),
        "projects": projects,
        "verticals": verticals,
        "repos": repos,
        "verdict_schema": {
            "full_name": "owner/repo",
            "verdict_text": "Brief evaluation of the repo",
            "project_relevance": {"project_name": "relevance description"},
            "recommendation": "investigate | skip | reject",
        },
    }


def save_verdicts(db, verdicts_json, scan_id=None, tokens_in=None,
                  tokens_out=None, web_searches=None):
    """Save a list of verdict dicts to the database.

    Each verdict dict must have: full_name, verdict_text, project_relevance.
    Optionally: reddit_validation.

    Wrapped in a transaction for atomicity + performance (#3).
    Batch-fetches repo IDs upfront to avoid N+1 (#3).
    """
    if scan_id is None:
        scan_id = get_latest_scan_id(db)
    if scan_id is None:
        raise ValueError("No scans exist in the database")

    # Batch-fetch all repo IDs in one query (#3)
    full_names = [v["full_name"] for v in verdicts_json]
    if not full_names:
        return {"saved": 0, "scan_id": scan_id}

    placeholders = ",".join("?" * len(full_names))
    rows = db.execute(
        f"SELECT id, full_name FROM repos WHERE full_name IN ({placeholders})",
        full_names
    ).fetchall()
    repo_id_map = {row[1]: row[0] for row in rows}

    saved = 0
    with db.conn:  # Transaction: atomic writes + batched WAL flushes (#3)
        for v in verdicts_json:
            repo_id = repo_id_map.get(v["full_name"])
            if repo_id is None:
                print(f"Warning: repo '{v['full_name']}' not found in DB, skipping")
                continue

            verdict_data = {
                "verdict_text": v["verdict_text"],
                "project_relevance": v.get("project_relevance", ""),
                "reddit_validation": v.get("reddit_validation", ""),
            }
            save_verdict(db, repo_id, scan_id, verdict_data)
            # Clear needs_verdict flag so this repo isn't re-evaluated
            db.execute(
                "UPDATE scan_snapshots SET needs_verdict = 0 WHERE repo_id = ? AND scan_id = ?",
                [repo_id, scan_id]
            )

            # Auto-annotation based on Claude recommendation
            # Only if no existing annotation (don't override human decisions)
            recommendation = v.get("recommendation", "").lower()
            if recommendation in ("reject", "investigate"):
                existing_ann = db.execute(
                    "SELECT status FROM annotations WHERE repo_id = ?",
                    [repo_id]
                ).fetchone()
                if existing_ann is None:
                    if recommendation == "reject":
                        save_annotation(
                            db, repo_id, "rejected",
                            reason=v.get("verdict_text", "Auto-rejected by Claude"),
                        )
                    elif recommendation == "investigate":
                        save_annotation(
                            db, repo_id, "watching",
                            notes="Auto-promoted by Claude: " + v.get("verdict_text", ""),
                        )

            saved += 1

        # Update scans.metadata with token tracking (inside same transaction)
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
