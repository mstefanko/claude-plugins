import tempfile
import unittest
from pathlib import Path

from tech_radar import db as db_module
from tech_radar.dashboard import TechRadarApp


def _repo_data(full_name):
    owner, repo_name = full_name.split("/", 1)
    return {
        "full_name": full_name,
        "owner": owner,
        "repo_name": repo_name,
        "description": f"{repo_name} description",
        "language": "Python",
        "topics": [],
        "url": f"https://github.com/{full_name}",
        "homepage": "",
        "license": "",
        "archived": 0,
        "is_fork": 0,
        "created_at": "2026-01-01",
        "pushed_at": "2026-04-28",
        "first_seen": "2026-04-01",
    }


def _snapshot(repo_id, scan_id, stars, category="general"):
    return {
        "repo_id": repo_id,
        "scan_id": scan_id,
        "stars": stars,
        "stars_delta": None,
        "stars_delta_pct": None,
        "stars_per_day": None,
        "category": category,
        "is_under_radar": 0,
        "is_rising": 0,
        "relevance_score": 0,
        "matched_keywords": [],
        "matched_projects": [],
        "reddit_validate": 0,
        "hn_context": "",
        "needs_verdict": 0,
    }


class DashboardQueryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "radar.db"
        self.db = db_module.open_db(str(self.db_path))

        self.scan1 = db_module.insert_scan(self.db, {
            "scan_date": "2026-04-01",
            "timeframe": "monthly",
            "github_queries": 0,
            "hn_queries": 0,
            "repos_found": 0,
            "repos_new": 0,
            "repos_returning": 0,
            "repos_rising": 0,
            "duration_seconds": 0.0,
            "metadata": "{}",
        })
        self.scan2 = db_module.insert_scan(self.db, {
            "scan_date": "2026-04-28",
            "timeframe": "monthly",
            "github_queries": 0,
            "hn_queries": 0,
            "repos_found": 0,
            "repos_new": 0,
            "repos_returning": 0,
            "repos_rising": 0,
            "duration_seconds": 0.0,
            "metadata": "{}",
        })

        self.old_only = self._add_repo("acme/old-only")
        db_module.insert_snapshot(self.db, _snapshot(self.old_only["id"], self.scan1, 10))

        self.continuing = self._add_repo("acme/continuing")
        db_module.insert_snapshot(self.db, _snapshot(self.continuing["id"], self.scan1, 15))
        db_module.insert_snapshot(self.db, _snapshot(self.continuing["id"], self.scan2, 25))
        db_module.save_annotation(self.db, self.continuing["id"], "watching")

        self.latest_only = self._add_repo("acme/latest-only")
        db_module.insert_snapshot(self.db, _snapshot(self.latest_only["id"], self.scan2, 20))

        self.rejected_old = self._add_repo("acme/rejected-old")
        db_module.insert_snapshot(self.db, _snapshot(self.rejected_old["id"], self.scan1, 30))
        db_module.save_annotation(self.db, self.rejected_old["id"], "rejected")

        self.app = TechRadarApp(db_path=str(self.db_path))
        self.app._db = self.db

    def tearDown(self):
        self.db.conn.close()
        self.tmp.cleanup()

    def _add_repo(self, full_name):
        return db_module.upsert_repo(self.db, _repo_data(full_name))

    def _query_names(self, tab):
        self.app._current_tab = tab
        sql, params = self.app._repo_query_sql(self.scan2, None)
        return [row[1] for row in self.db.execute(sql, params).fetchall()]

    def test_all_uses_latest_snapshot_per_repo_and_excludes_rejected(self):
        self.assertEqual(
            self._query_names("All"),
            ["acme/continuing", "acme/latest-only", "acme/old-only"],
        )

    def test_latest_tab_uses_latest_scan_only(self):
        self.assertEqual(
            self._query_names("Latest"),
            ["acme/continuing", "acme/latest-only"],
        )

    def test_status_tabs_are_all_time_not_latest_scan_only(self):
        self.assertEqual(self._query_names("Rejected"), ["acme/rejected-old"])
        self.assertEqual(self._query_names("Watching"), ["acme/continuing"])

    def test_tab_counts_split_all_time_from_latest_scan(self):
        counts = self.app._status_counts(self.scan2, None)
        self.assertEqual(counts["All"], 3)
        self.assertEqual(counts["Latest"], 2)
        self.assertEqual(counts["Watching"], 1)
        self.assertEqual(counts["Rejected"], 1)


if __name__ == "__main__":
    unittest.main()
