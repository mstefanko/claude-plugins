"""Database module: schema creation, migration, queries, FTS setup.

Uses sqlite-utils for ergonomic table creation, upsert, and FTS5 management.
All tables are created via ensure_schema() on first open.
"""

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

import sqlite_utils

DEFAULT_DB_PATH = os.path.expanduser("~/.tech-radar/radar.db")
SCHEMA_VERSION = 1


def open_db(path=None):
    """Open (or create) the tech-radar database.

    Sets WAL journal mode for concurrent read/write, then ensures schema exists.
    Returns a sqlite_utils.Database instance.
    """
    if path is None:
        path = DEFAULT_DB_PATH
    # Ensure parent directory exists
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite_utils.Database(path)
    db.execute("PRAGMA journal_mode=WAL")
    ensure_schema(db)
    return db


def ensure_schema(db):
    """Create all tables if they don't already exist, enable FTS with triggers."""
    # -- scans (must exist before scan_snapshots FK) --
    if "scans" not in db.table_names():
        db["scans"].create({
            "id": int,
            "scan_date": str,
            "timeframe": str,
            "github_queries": int,
            "hn_queries": int,
            "repos_found": int,
            "repos_new": int,
            "repos_returning": int,
            "repos_rising": int,
            "duration_seconds": float,
            "metadata": str,
        }, pk="id")
        db.execute("CREATE INDEX IF NOT EXISTS idx_scans_date ON scans(scan_date)")

    # -- repos --
    if "repos" not in db.table_names():
        db["repos"].create({
            "id": int,
            "full_name": str,
            "owner": str,
            "repo_name": str,
            "description": str,
            "language": str,
            "topics": str,
            "url": str,
            "homepage": str,
            "license": str,
            "archived": int,
            "is_fork": int,
            "created_at": str,
            "pushed_at": str,
            "first_seen": str,
            "last_seen": str,
        }, pk="id", not_null={"full_name", "owner", "repo_name", "url", "first_seen", "last_seen"})
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_repos_full_name ON repos(full_name)")

    # -- scan_snapshots --
    if "scan_snapshots" not in db.table_names():
        db["scan_snapshots"].create({
            "id": int,
            "repo_id": int,
            "scan_id": int,
            "stars": int,
            "stars_delta": int,
            "stars_delta_pct": float,
            "stars_per_day": float,
            "category": str,
            "is_under_radar": int,
            "is_rising": int,
            "relevance_score": int,
            "matched_keywords": str,
            "matched_projects": str,
            "reddit_validate": int,
            "hn_context": str,
            "needs_verdict": int,
        }, pk="id", not_null={"repo_id", "scan_id", "stars", "category"},
           defaults={"is_under_radar": 0, "is_rising": 0, "reddit_validate": 0, "needs_verdict": 1},
           foreign_keys=[("repo_id", "repos", "id"), ("scan_id", "scans", "id")])
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshots_repo_scan ON scan_snapshots(repo_id, scan_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_repo ON scan_snapshots(repo_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_scan ON scan_snapshots(scan_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_category ON scan_snapshots(category)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_under_radar ON scan_snapshots(is_under_radar) WHERE is_under_radar = 1")
        db.execute("CREATE INDEX IF NOT EXISTS idx_snapshots_rising ON scan_snapshots(is_rising) WHERE is_rising = 1")

    # -- verdicts --
    if "verdicts" not in db.table_names():
        db["verdicts"].create({
            "id": int,
            "repo_id": int,
            "scan_id": int,
            "verdict_text": str,
            "project_relevance": str,
            "reddit_validation": str,
            "generated_at": str,
        }, pk="id", not_null={"repo_id", "scan_id", "verdict_text", "generated_at"},
           foreign_keys=[("repo_id", "repos", "id"), ("scan_id", "scans", "id")])
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_verdicts_repo_scan ON verdicts(repo_id, scan_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_verdicts_repo ON verdicts(repo_id)")

    # -- annotations --
    if "annotations" not in db.table_names():
        db["annotations"].create({
            "id": int,
            "repo_id": int,
            "status": str,
            "notes": str,
            "tested_date": str,
            "rejection_reason": str,
            "updated_at": str,
        }, pk="id", not_null={"repo_id", "status", "updated_at"},
           defaults={"status": "new"},
           foreign_keys=[("repo_id", "repos", "id")])
        db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_annotations_repo ON annotations(repo_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_annotations_status ON annotations(status)")

    # -- meta --
    if "meta" not in db.table_names():
        db["meta"].create({
            "schema_version": int,
            "created_at": str,
        }, pk=None)
        db["meta"].insert({
            "schema_version": SCHEMA_VERSION,
            "created_at": _now_iso(),
        })

    # -- FTS indexes (with triggers for auto-sync) --
    _enable_fts_safe(db, "repos", ["full_name", "description", "language", "topics"])
    _enable_fts_safe(db, "verdicts", ["verdict_text", "reddit_validation"])


def _enable_fts_safe(db, table_name, columns):
    """Enable FTS5 on a table if not already enabled."""
    fts_table = f"{table_name}_fts"
    if fts_table not in db.table_names():
        db[table_name].enable_fts(columns, create_triggers=True)


def _now_iso():
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# CRUD helpers
# ---------------------------------------------------------------------------

def upsert_repo(db, repo_data):
    """Upsert a repo by full_name. Returns the repo row dict.

    repo_data must contain 'full_name'. Other fields are updated on conflict.
    """
    full_name = repo_data["full_name"]
    # Split owner/repo_name if not provided
    if "owner" not in repo_data or "repo_name" not in repo_data:
        parts = full_name.split("/", 1)
        repo_data.setdefault("owner", parts[0])
        repo_data.setdefault("repo_name", parts[1] if len(parts) > 1 else full_name)
    # Ensure first_seen/last_seen
    now = _now_iso()
    repo_data.setdefault("first_seen", now)
    repo_data["last_seen"] = now
    # Serialize topics if it's a list
    if isinstance(repo_data.get("topics"), list):
        repo_data["topics"] = json.dumps(repo_data["topics"])
    # Upsert — update everything except first_seen on conflict
    existing = get_repo_by_name(db, full_name)
    if existing:
        # Preserve first_seen from existing record
        repo_data["first_seen"] = existing["first_seen"]
        db["repos"].update(existing["id"], repo_data)
        return db["repos"].get(existing["id"])
    else:
        db["repos"].insert(repo_data)
        return get_repo_by_name(db, full_name)


def insert_scan(db, scan_data):
    """Insert a scan record. Returns the new scan_id."""
    return db["scans"].insert(scan_data, pk="id").last_pk


def insert_snapshot(db, snapshot_data):
    """Insert a scan_snapshot record."""
    # Serialize JSON arrays if needed
    for field in ("matched_keywords", "matched_projects"):
        if isinstance(snapshot_data.get(field), list):
            snapshot_data[field] = json.dumps(snapshot_data[field])
    db["scan_snapshots"].insert(snapshot_data)


def get_latest_scan_id(db):
    """Return the most recent scan_id, or None if no scans exist."""
    row = list(db.execute("SELECT id FROM scans ORDER BY id DESC LIMIT 1").fetchall())
    return row[0][0] if row else None


def get_repo_by_name(db, full_name):
    """Look up a repo by full_name. Returns the row dict or None."""
    rows = list(db["repos"].rows_where("full_name = ?", [full_name]))
    return rows[0] if rows else None


def get_previous_stars(db, repo_id):
    """Return the star count from the most recent snapshot for a repo, or None."""
    row = list(db.execute(
        "SELECT stars FROM scan_snapshots WHERE repo_id = ? ORDER BY scan_id DESC LIMIT 1",
        [repo_id]
    ).fetchall())
    return row[0][0] if row else None


def save_verdict(db, repo_id, scan_id, verdict_data):
    """Insert or replace a verdict for a repo+scan combination.

    verdict_data should contain: verdict_text, and optionally
    project_relevance (dict/str), reddit_validation (str).
    """
    record = {
        "repo_id": repo_id,
        "scan_id": scan_id,
        "verdict_text": verdict_data["verdict_text"],
        "project_relevance": verdict_data.get("project_relevance", ""),
        "reddit_validation": verdict_data.get("reddit_validation", ""),
        "generated_at": _now_iso(),
    }
    # Serialize project_relevance if dict
    if isinstance(record["project_relevance"], dict):
        record["project_relevance"] = json.dumps(record["project_relevance"])
    # Upsert by repo_id + scan_id (unique constraint)
    existing = db.execute(
        "SELECT id FROM verdicts WHERE repo_id = ? AND scan_id = ?",
        [repo_id, scan_id]
    ).fetchone()
    if existing:
        db["verdicts"].update(existing[0], record)
    else:
        db["verdicts"].insert(record)


def save_annotation(db, repo_id, status, notes=None, reason=None):
    """Insert or update an annotation for a repo.

    status: new | watching | tested | adopted | rejected | archived
    """
    record = {
        "repo_id": repo_id,
        "status": status,
        "notes": notes or "",
        "updated_at": _now_iso(),
    }
    if status == "rejected" and reason:
        record["rejection_reason"] = reason
    if status == "tested":
        record["tested_date"] = _now_iso()
    # Upsert by repo_id
    existing = list(db["annotations"].rows_where("repo_id = ?", [repo_id]))
    if existing:
        db["annotations"].update(existing[0]["id"], record)
    else:
        db["annotations"].insert(record)


def compute_needs_verdict(db, repo_id, current_stars):
    """Determine if a repo needs a fresh Claude verdict.

    Rules:
    - rejected annotation -> never re-evaluate
    - watching annotation -> always refresh
    - no previous verdict -> needs verdict
    - tested/adopted annotation -> only if stars changed >50%
    - default -> if stars changed >20%
    """
    annotation = db.execute(
        "SELECT status FROM annotations WHERE repo_id = ?", [repo_id]
    ).fetchone()

    if annotation:
        status = annotation[0]
        if status == "rejected":
            return False  # never re-evaluate rejected repos
        if status == "watching":
            return True   # always refresh watched repos

    # Check star delta since last verdict
    last_verdict_scan = db.execute("""
        SELECT ss.stars FROM verdicts v
        JOIN scan_snapshots ss ON ss.scan_id = v.scan_id AND ss.repo_id = v.repo_id
        WHERE v.repo_id = ?
        ORDER BY v.generated_at DESC LIMIT 1
    """, [repo_id]).fetchone()

    if not last_verdict_scan:
        return True  # no previous verdict

    prev_stars = last_verdict_scan[0]
    if prev_stars == 0:
        return True

    delta_pct = abs(current_stars - prev_stars) / prev_stars * 100
    threshold = 50 if annotation and annotation[0] in ("tested", "adopted") else 20
    return delta_pct >= threshold


def get_annotation_status(db, repo_id):
    """Return annotation status for a repo, or None if no annotation exists."""
    row = db.execute(
        "SELECT status FROM annotations WHERE repo_id = ?", [repo_id]
    ).fetchone()
    return row[0] if row else None


def search_fts(db, query, table="repos"):
    """Search FTS index. Returns list of row dicts from the base table.

    table: 'repos' or 'verdicts'
    """
    fts_table = f"{table}_fts"
    if fts_table not in db.table_names():
        return []
    results = list(db[table].search(query))
    return results


# ---------------------------------------------------------------------------
# Migration from history.json
# ---------------------------------------------------------------------------

def migrate_from_history(db, history_path=None):
    """One-time migration: reads history.json, imports into the database.

    Creates a single synthetic scan, imports all repos with one snapshot each.
    Renames history.json to history.json.bak after successful migration.
    """
    if history_path is None:
        history_path = os.path.expanduser("~/.tech-radar/history.json")

    if not os.path.exists(history_path):
        raise FileNotFoundError(f"History file not found: {history_path}")

    with open(history_path, "r") as f:
        data = json.load(f)

    repos_data = data.get("repos", {})
    scans_data = data.get("scans", [])

    if not repos_data:
        print("No repos found in history.json — nothing to migrate.")
        return

    # Determine the earliest scan date for the synthetic scan
    earliest_date = None
    if scans_data:
        dates = [s.get("date", "") for s in scans_data if s.get("date")]
        if dates:
            earliest_date = min(dates)
    if not earliest_date:
        earliest_date = _now_iso()[:10]  # fallback to today

    # Create a synthetic scan entry
    scan_id = insert_scan(db, {
        "scan_date": earliest_date,
        "timeframe": "migration",
        "github_queries": 0,
        "hn_queries": 0,
        "repos_found": len(repos_data),
        "repos_new": len(repos_data),
        "repos_returning": 0,
        "repos_rising": 0,
        "duration_seconds": 0.0,
        "metadata": json.dumps({
            "source": "history.json",
            "migration_date": _now_iso(),
            "original_scans": len(scans_data),
        }),
    })

    imported = 0
    for full_name, repo_info in repos_data.items():
        # Parse owner/repo from the key
        parts = full_name.split("/", 1)
        owner = parts[0]
        repo_name = parts[1] if len(parts) > 1 else full_name

        first_seen = repo_info.get("first_seen", earliest_date)
        last_seen = repo_info.get("last_seen", earliest_date)
        stars = repo_info.get("stars_last", 0)

        # Upsert repo
        repo_row = upsert_repo(db, {
            "full_name": full_name,
            "owner": owner,
            "repo_name": repo_name,
            "description": "",
            "language": "",
            "topics": "[]",
            "url": f"https://github.com/{full_name}",
            "homepage": "",
            "license": "",
            "archived": 0,
            "is_fork": 0,
            "created_at": "",
            "pushed_at": "",
            "first_seen": first_seen,
            "last_seen": last_seen,
        })

        # Create one snapshot with the most recent star count
        insert_snapshot(db, {
            "repo_id": repo_row["id"],
            "scan_id": scan_id,
            "stars": stars,
            "stars_delta": None,
            "stars_delta_pct": None,
            "stars_per_day": None,
            "category": "general",  # unknown from history — default to general
            "is_under_radar": 0,
            "is_rising": 0,
            "relevance_score": None,
            "matched_keywords": "[]",
            "matched_projects": "[]",
            "reddit_validate": 0,
            "hn_context": "",
            "needs_verdict": 0,  # historical — no verdict needed
        })

        imported += 1

    # Rename history.json to .bak
    bak_path = history_path + ".bak"
    if os.path.exists(bak_path):
        # If .bak already exists, remove it first
        os.remove(bak_path)
    shutil.move(history_path, bak_path)

    print(f"Migration complete: {imported} repos imported from history.json")
    print(f"Synthetic scan created (id={scan_id}, date={earliest_date})")
    print(f"Original file backed up to: {bak_path}")
