"""External source fetchers: awesome lists, topic searches, batch enrichment.

Provides broader discovery via curated lists and GitHub topics beyond
the keyword-driven gather pipeline.
"""

import base64
import concurrent.futures
import re
import sys
import time
from datetime import datetime, timezone
from typing import Optional

from .constants import (
    MAX_ENRICHMENT_BATCH,
    MAX_STARS_DEFAULT,
    PER_REQUEST_DELAY,
    THREAD_POOL_SIZE,
)


def warn(msg: str) -> None:
    print(f"tech-radar: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Awesome-list parser
# ---------------------------------------------------------------------------

_GITHUB_REPO_RE = re.compile(
    r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
)


def fetch_awesome_list(repo_slug: str, token: Optional[str]) -> list[str]:
    """Parse an awesome-list README for GitHub repo URLs.

    Args:
        repo_slug: e.g. "awesome-selfhosted/awesome-selfhosted"
        token: GitHub API token

    Returns:
        List of "owner/repo" strings found in the README.
    """
    from .gather import github_request

    url = f"https://api.github.com/repos/{repo_slug}/readme"
    try:
        data = github_request(url, token)
    except Exception as exc:
        warn(f"Failed to fetch README for {repo_slug}: {exc}")
        return []

    content_b64 = data.get("content", "")
    try:
        readme_text = base64.b64decode(content_b64).decode("utf-8", errors="replace")
    except Exception:
        warn(f"Failed to decode README for {repo_slug}")
        return []

    matches = _GITHUB_REPO_RE.findall(readme_text)

    # Deduplicate preserving order, clean trailing dots/slashes
    seen = set()
    repos = []
    for match in matches:
        slug = match.rstrip("./")
        # Skip the awesome list itself and common non-repo paths
        if slug.lower() == repo_slug.lower():
            continue
        if slug.lower() in seen:
            continue
        seen.add(slug.lower())
        repos.append(slug)

    return repos


# ---------------------------------------------------------------------------
# Topic search
# ---------------------------------------------------------------------------

def fetch_repos_by_topic(topic: str, min_stars: int, token: Optional[str],
                         date_from: str) -> list[dict]:
    """Search GitHub for repos with a given topic, recent activity, and min stars.

    Returns raw GitHub API items (same shape as Search API results).
    """
    from .gather import github_request
    from .constants import GITHUB_SEARCH_REPOS

    q = f"topic:{topic}+stars:>{min_stars}+pushed:>{date_from}"
    url = f"{GITHUB_SEARCH_REPOS}?q={q}&sort=stars&order=desc&per_page=30"

    try:
        data = github_request(url, token)
        return data.get("items", [])
    except Exception as exc:
        warn(f"Topic search '{topic}' failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Code search (for MCP vertical)
# ---------------------------------------------------------------------------

def fetch_repos_by_code_search(query: str, token: Optional[str]) -> list[str]:
    """Search GitHub code and return unique repo full_names.

    Returns list of "owner/repo" strings.
    """
    from .gather import github_request
    from .constants import GITHUB_SEARCH_CODE

    url = f"{GITHUB_SEARCH_CODE}?q={query}&per_page=30"

    try:
        data = github_request(url, token)
        seen = set()
        repos = []
        for item in data.get("items", []):
            repo_info = item.get("repository", {})
            full_name = repo_info.get("full_name", "")
            if full_name and full_name not in seen:
                seen.add(full_name)
                repos.append(full_name)
        return repos
    except Exception as exc:
        warn(f"Code search '{query}' failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Batch enrichment
# ---------------------------------------------------------------------------

def _fetch_single_repo(full_name: str, token: Optional[str]) -> Optional[dict]:
    """Fetch metadata for a single repo via REST API."""
    from .gather import github_request

    url = f"https://api.github.com/repos/{full_name}"
    try:
        time.sleep(PER_REQUEST_DELAY)
        return github_request(url, token)
    except Exception as exc:
        warn(f"Failed to fetch {full_name}: {exc}")
        return None


def enrich_repo_metadata(full_names: list[str], token: Optional[str],
                         db, date_from: str) -> list[dict]:
    """Batch-fetch metadata for repos not already in the DB.

    Applies cross-scan dedup (skips repos already in `repos` table),
    activity gate (discards stale repos), and star ceiling.

    Returns items in the same shape as GitHub Search API results.
    """
    if not full_names:
        return []

    # Cross-scan dedup: skip repos already in DB
    placeholders = ",".join("?" * len(full_names))
    existing_rows = db.execute(
        f"SELECT full_name FROM repos WHERE full_name IN ({placeholders})",
        full_names
    ).fetchall()
    existing_names = {row[0].lower() for row in existing_rows}

    to_fetch = [fn for fn in full_names if fn.lower() not in existing_names]

    if not to_fetch:
        return []

    # Cap at MAX_ENRICHMENT_BATCH
    if len(to_fetch) > MAX_ENRICHMENT_BATCH:
        warn(f"Capping enrichment batch from {len(to_fetch)} to {MAX_ENRICHMENT_BATCH}")
        to_fetch = to_fetch[:MAX_ENRICHMENT_BATCH]

    warn(f"Enriching {len(to_fetch)} new repos from external sources")

    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE) as pool:
        futures = {
            pool.submit(_fetch_single_repo, fn, token): fn
            for fn in to_fetch
        }
        for future in concurrent.futures.as_completed(futures):
            data = future.result()
            if data is None:
                continue

            # Activity gate: discard repos not pushed within scan timeframe
            pushed_at = data.get("pushed_at", "")
            if pushed_at and pushed_at[:10] < date_from:
                continue

            # Star ceiling: discard mega-repos
            stars = data.get("stargazers_count", 0)
            if stars > MAX_STARS_DEFAULT:
                continue

            results.append(data)

    return results


# ---------------------------------------------------------------------------
# Broad trending query
# ---------------------------------------------------------------------------

def fetch_broad_trending(token: Optional[str], date_from: str) -> list[dict]:
    """Fetch recently-created repos with significant stars (general discovery).

    Uses stars:500..50000 and created:>{6mo_ago} to find rising repos
    outside of specific verticals.
    """
    from .gather import github_request
    from .constants import GITHUB_SEARCH_REPOS

    six_months_ago = datetime.now(timezone.utc).replace(
        month=max(1, datetime.now(timezone.utc).month - 6)
    ).strftime("%Y-%m-%d")

    q = f"stars:500..{MAX_STARS_DEFAULT}+created:>{six_months_ago}"
    url = f"{GITHUB_SEARCH_REPOS}?q={q}&sort=stars&order=desc&per_page=30"

    try:
        data = github_request(url, token)
        return data.get("items", [])
    except Exception as exc:
        warn(f"Broad trending query failed: {exc}")
        return []


# ---------------------------------------------------------------------------
# Vertical pipeline orchestrator
# ---------------------------------------------------------------------------

def fetch_vertical_repos(vertical_name: str, vertical_config: dict,
                         token: Optional[str], date_from: str,
                         db) -> list[dict]:
    """Fetch all repos for a single vertical from all configured sources.

    Collects full_names from awesome lists, seed repos, topic searches,
    and code searches. Deduplicates, then batch-enriches new repos.

    Returns list of GitHub API-shaped dicts (ready for parse_repo_item).
    """
    all_full_names = set()

    # 1. Seed repos (always included)
    for slug in vertical_config.get("seed_repos", []):
        all_full_names.add(slug)

    # 2. Awesome lists
    for list_slug in vertical_config.get("awesome_lists", []):
        warn(f"  [{vertical_name}] Fetching awesome list: {list_slug}")
        repos = fetch_awesome_list(list_slug, token)
        warn(f"  [{vertical_name}]   Found {len(repos)} repos in {list_slug}")
        all_full_names.update(repos)

    # 3. Topic searches
    min_stars = vertical_config.get("min_stars", 100)
    for topic in vertical_config.get("github_topics", []):
        warn(f"  [{vertical_name}] Topic search: {topic}")
        items = fetch_repos_by_topic(topic, min_stars, token, date_from)
        for item in items:
            fn = item.get("full_name", "")
            if fn:
                all_full_names.add(fn)
        warn(f"  [{vertical_name}]   Found {len(items)} repos for topic '{topic}'")

    # 4. Code searches (MCP vertical)
    for query in vertical_config.get("code_searches", []):
        warn(f"  [{vertical_name}] Code search: {query}")
        repos = fetch_repos_by_code_search(query, token)
        all_full_names.update(repos)
        warn(f"  [{vertical_name}]   Found {len(repos)} repos via code search")

    warn(f"  [{vertical_name}] Total unique candidates: {len(all_full_names)}")

    # 5. Batch enrich (skips repos already in DB)
    enriched = enrich_repo_metadata(list(all_full_names), token, db, date_from)
    warn(f"  [{vertical_name}] Enriched {len(enriched)} new repos")

    return enriched


def fetch_all_verticals(config: dict, token: Optional[str],
                        date_from: str, db) -> dict[str, list[dict]]:
    """Fetch repos for all configured verticals.

    Returns {vertical_name: [github_api_items]}.
    """
    verticals = config.get("verticals", {})
    if not verticals:
        return {}

    warn(f"Fetching external sources for {len(verticals)} verticals")
    results = {}

    for name, vcfg in verticals.items():
        warn(f"Processing vertical: {name}")
        items = fetch_vertical_repos(name, vcfg, token, date_from, db)
        results[name] = items

    return results
