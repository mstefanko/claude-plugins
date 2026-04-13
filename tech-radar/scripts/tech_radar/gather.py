"""Gather module: scan GitHub and HN for trending repos, write results to SQLite.

Extracts all gather/fetch/parse/score/select logic from the original
tech-radar-gather monolith. The terminal step writes to SQLite via db.py
instead of building JSON output.
"""

import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional

from .constants import (
    BROAD_KEYWORD_THRESHOLD,
    CONTROVERSY_THRESHOLD,
    DIVERSITY_SLOTS,
    GITHUB_SEARCH_CODE,
    GITHUB_SEARCH_REPOS,
    HN_ALGOLIA_SEARCH,
    HN_MIN_POINTS,
    MAX_HN_STORIES,
    MAX_RESULTS,
    MAX_UNDER_RADAR,
    PER_REQUEST_DELAY,
    PRIMARY_KEYWORDS,
    RATE_LIMIT_BATCH_PAUSE,
    RATE_LIMIT_BATCH_SIZE,
    SKIP_TESTING_TOOLS,
    STAR_TIERS,
    THREAD_POOL_SIZE,
    TIMEFRAME_DAYS,
    UNAUTHENTICATED_DELAY,
    UNAUTHENTICATED_MAX_QUERIES,
)
from . import sources as sources_module
from .normalize import (
    fuzzy_match_keyword,
    looks_like_version,
    normalize,
    strip_version,
)
from . import db as db_module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def warn(msg: str) -> None:
    print(f"tech-radar: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DEFAULT_CONFIG = {
    "projects": {},
    "interests": [],
    "phrase_queries": [],
    "min_stars": 1000,
}


def load_config(path: str = "~/.tech-radar.json") -> dict:
    expanded = os.path.expanduser(path)
    if os.path.isfile(expanded):
        try:
            with open(expanded, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            warn(f"Could not load config {expanded}: {exc}")
    else:
        warn(f"Config not found at {expanded}, using defaults")
    return dict(DEFAULT_CONFIG)


def resolve_github_token() -> Optional[str]:
    """Resolve GitHub token: GITHUB_TOKEN env var > gh CLI > None."""
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


# ---------------------------------------------------------------------------
# Inverted index & query builder
# ---------------------------------------------------------------------------

def build_inverted_index(projects: dict) -> tuple:
    """keyword (normalized, version-stripped) -> set of project names, plus broad keyword set."""
    index = {}
    for proj_name, proj_data in projects.items():
        for category in ("backend", "frontend", "infra", "migrating_from", "migrating_to"):
            for raw_kw in proj_data.get(category, []):
                kw = normalize(strip_version(raw_kw))
                if not kw:
                    continue
                index.setdefault(kw, set()).add(proj_name)
    broad = {kw for kw, projs in index.items() if len(projs) >= BROAD_KEYWORD_THRESHOLD}
    return index, broad


def cluster_keywords(index: dict) -> list:
    """Group keywords that map to the exact same project set."""
    clusters = {}
    for kw, proj_set in index.items():
        key = frozenset(proj_set)
        clusters.setdefault(key, []).append(kw)
    return [(kws, projs) for projs, kws in clusters.items()]


def should_skip_keyword(kw: str, proj_set: set) -> bool:
    """Return True if keyword is too specific to be worth a query."""
    if kw in PRIMARY_KEYWORDS:
        return False
    if len(proj_set) > 1:
        return False
    if kw in SKIP_TESTING_TOOLS:
        return True
    if looks_like_version(kw):
        return True
    return False


def _batch_or_keywords(keywords: list, max_terms: int = 6) -> list:
    """Group keywords into OR-combined query strings with max_terms per batch.

    GitHub REST API supports OR between search terms but silently caps at
    6 OR operands — queries with 7+ terms return HTTP 422.
    """
    batches = []
    current_parts = []

    for kw in keywords:
        if " " in kw:
            encoded = urllib.parse.quote(f'"{kw}"')
        else:
            encoded = urllib.parse.quote(kw)

        current_parts.append(encoded)

        if len(current_parts) >= max_terms:
            batches.append("+OR+".join(current_parts))
            current_parts = []

    if current_parts:
        batches.append("+OR+".join(current_parts))

    return batches


def build_queries(config: dict) -> list:
    """Return list of (label, query_string, search_type, query_type) tuples."""
    projects = config.get("projects", {})
    interests = config.get("interests", [])

    index, _ = build_inverted_index(projects)
    clusters = cluster_keywords(index)

    queries = []

    # Stack-match queries: collect all keywords (deduped), batch with OR
    all_stack_kws = []
    seen_stack = set()
    for keywords, proj_set in clusters:
        for kw in keywords:
            if kw not in seen_stack and not should_skip_keyword(kw, proj_set):
                seen_stack.add(kw)
                all_stack_kws.append(kw)

    for i, batch_q in enumerate(_batch_or_keywords(all_stack_kws)):
        label = f"stack:batch-{i}"
        queries.append((label, batch_q, "repos", "stack"))

    # Interest queries: batch with OR
    for i, batch_q in enumerate(_batch_or_keywords(interests)):
        label = f"interest:batch-{i}"
        queries.append((label, batch_q, "repos", "interest"))

    # Phrase queries (exact multi-word matches)
    for phrase in config.get("phrase_queries", []):
        label = f"phrase:{phrase}"
        q_kw = f'"{"+".join(urllib.parse.quote(word) for word in phrase.split())}"'
        queries.append((label, q_kw, "repos", "phrase"))

    # Plugin discovery
    queries.append(("plugin-discovery", "filename:plugin.json+path:.claude-plugin", "code", "code"))

    return queries


# ---------------------------------------------------------------------------
# HN query builder
# ---------------------------------------------------------------------------

def build_hn_keywords(config: dict) -> list:
    """Extract deduplicated primary keywords for HN Algolia queries."""
    seen = set()
    keywords = []
    projects = config.get("projects", {})
    interests = config.get("interests", [])

    for proj_name, proj_data in projects.items():
        backend = proj_data.get("backend", [])
        for raw_kw in backend[:2]:
            kw = normalize(strip_version(raw_kw))
            if kw and kw not in seen:
                seen.add(kw)
                keywords.append((f"hn-stack:{proj_name}:{kw}", kw))

    for interest in interests:
        kw = normalize(interest)
        if kw not in seen:
            seen.add(kw)
            keywords.append((f"hn-interest:{kw}", kw))

    for phrase in config.get("phrase_queries", []):
        phrase_lower = phrase.lower()
        if phrase_lower not in seen:
            seen.add(phrase_lower)
            keywords.append((f"hn-phrase:{phrase_lower}", f'"{phrase}"'))

    return keywords


# ---------------------------------------------------------------------------
# Date range
# ---------------------------------------------------------------------------

def date_range(timeframe: str):
    now = datetime.now(timezone.utc)
    days = TIMEFRAME_DAYS[timeframe]
    date_from = (now - timedelta(days=days)).strftime("%Y-%m-%d")
    date_to = now.strftime("%Y-%m-%d")
    return date_from, date_to


def date_to_unix(date_str: str) -> int:
    """Convert YYYY-MM-DD to Unix timestamp."""
    dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------

def github_request(url: str, token: Optional[str]) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "tech-radar-gather/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)  # Stream-parse, no intermediate copy (#12)


def build_repo_url(q_keywords: str, date_from: str, min_stars: int) -> str:
    q = f"{q_keywords}+created:>{date_from}+stars:>{min_stars}"
    return f"{GITHUB_SEARCH_REPOS}?q={q}&sort=stars&order=desc&per_page=30"


def build_merged_stack_url(q_keywords: str, date_from: str) -> str:
    """Stack queries use stars:>100 and post-filter by min_stars threshold."""
    q = f"{q_keywords}+created:>{date_from}+stars:>100"
    return f"{GITHUB_SEARCH_REPOS}?q={q}&sort=stars&order=desc&per_page=30"


def build_code_url(q_keywords: str) -> str:
    return f"{GITHUB_SEARCH_CODE}?q={q_keywords}&per_page=30"


def build_interest_url(q_keywords: str, date_from: str, min_stars: int) -> str:
    """Interest queries find established repos with recent activity."""
    q = f"{q_keywords}+pushed:>{date_from}+stars:>{min_stars}"
    return f"{GITHUB_SEARCH_REPOS}?q={q}&sort=stars&order=desc&per_page=30"


def fetch_query(label: str, q_keywords: str, search_type: str,
                query_type: str, date_from: str, min_stars: int,
                token: Optional[str]) -> dict:
    """Execute a single GitHub search query. Returns parsed JSON or error dict."""
    try:
        if query_type == "code":
            url = build_code_url(q_keywords)
        elif query_type == "stack":
            url = build_merged_stack_url(q_keywords, date_from)
        elif query_type in ("interest", "phrase"):
            url = build_interest_url(q_keywords, date_from, min_stars)
        else:
            url = build_repo_url(q_keywords, date_from, min_stars)

        data = github_request(url, token)
        return {"label": label, "query_type": query_type,
                "search_type": search_type, "items": data.get("items", []),
                "total_count": data.get("total_count", 0)}
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        warn(f"Query '{label}' failed: {exc}")
        return {"label": label, "query_type": query_type,
                "search_type": search_type, "items": [], "error": str(exc)}


def fetch_all_github(queries: list, date_from: str, min_stars: int,
                     token: Optional[str]) -> tuple:
    """Fire all queries, return (results_list, error_message_or_None)."""
    results = []
    has_error = False

    if token:
        batches = [queries[i:i + RATE_LIMIT_BATCH_SIZE]
                   for i in range(0, len(queries), RATE_LIMIT_BATCH_SIZE)]
        # Single pool reused across batches (#16)
        with concurrent.futures.ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE) as pool:
            for batch_idx, batch in enumerate(batches):
                if batch_idx > 0:
                    warn(f"Rate-limit pause: waiting {RATE_LIMIT_BATCH_PAUSE}s before batch "
                         f"{batch_idx + 1}/{len(batches)}")
                    time.sleep(RATE_LIMIT_BATCH_PAUSE)
                futures = {
                    pool.submit(fetch_query, label, q_kw, stype, qtype,
                                date_from, min_stars, token): label
                    for label, q_kw, stype, qtype in batch
                }
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    if "error" in result:
                        has_error = True
                    results.append(result)
    else:
        warn("No GitHub auth found. Set GITHUB_TOKEN or run `gh auth login`. "
             "Using unauthenticated mode (max {} queries, "
             "{}s delay).".format(UNAUTHENTICATED_MAX_QUERIES, UNAUTHENTICATED_DELAY))
        for i, (label, q_kw, stype, qtype) in enumerate(queries[:UNAUTHENTICATED_MAX_QUERIES]):
            if i > 0:
                time.sleep(UNAUTHENTICATED_DELAY)
            result = fetch_query(label, q_kw, stype, qtype, date_from, min_stars, token)
            if "error" in result:
                has_error = True
            results.append(result)

    error_msg = "one or more queries failed" if has_error else None
    return results, error_msg


# ---------------------------------------------------------------------------
# HN Algolia API
# ---------------------------------------------------------------------------

def hn_request(url: str) -> dict:
    headers = {"User-Agent": "tech-radar-gather/1.0"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)  # Stream-parse (#12)


def fetch_hn_query(label: str, keyword: str, since_unix: int) -> dict:
    """Execute a single HN Algolia search query."""
    try:
        params = urllib.parse.urlencode({
            "query": keyword,
            "tags": "story",
            "numericFilters": f"created_at_i>{since_unix},points>{HN_MIN_POINTS}",
            "hitsPerPage": "10",
        })
        url = f"{HN_ALGOLIA_SEARCH}?{params}"
        data = hn_request(url)
        return {"label": label, "hits": data.get("hits", []), "keyword": keyword}
    except (urllib.error.HTTPError, urllib.error.URLError, OSError) as exc:
        warn(f"HN query '{label}' failed: {exc}")
        return {"label": label, "hits": [], "keyword": keyword, "error": str(exc)}


def fetch_all_hn(hn_keywords: list, since_unix: int) -> tuple:
    """Fire all HN queries concurrently. Returns (results_list, error_msg_or_None)."""
    results = []
    has_error = False

    with concurrent.futures.ThreadPoolExecutor(max_workers=THREAD_POOL_SIZE) as pool:
        futures = {
            pool.submit(fetch_hn_query, label, kw, since_unix): label
            for label, kw in hn_keywords
        }
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if "error" in result:
                has_error = True
            results.append(result)

    error_msg = "one or more HN queries failed" if has_error else None
    return results, error_msg


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_repo_item(item: dict) -> dict:
    """Normalize a GitHub API item into our repo schema.

    Includes enrichment fields: homepage, license, archived, is_fork.
    """
    full_name = item.get("full_name", "")
    parts = full_name.split("/", 1)
    owner = parts[0] if len(parts) == 2 else ""
    name = parts[1] if len(parts) == 2 else full_name

    created_str = item.get("created_at", "")
    created_date = created_str[:10] if created_str else ""
    pushed_str = item.get("pushed_at", "")
    pushed_date = pushed_str[:10] if pushed_str else ""
    stars = item.get("stargazers_count", 0)

    # Compute stars_per_day
    days_since = 1
    if created_str:
        try:
            created_dt = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            delta = datetime.now(timezone.utc) - created_dt
            days_since = max(1, delta.days)
        except (ValueError, TypeError):
            pass

    return {
        "id": full_name,
        "source": "github",
        "name": name,
        "owner": owner,
        "description": item.get("description", "") or "",
        "url": item.get("html_url", ""),
        "stars": stars,
        "language": item.get("language", "") or "",
        "topics": item.get("topics", []),
        "created": created_date,
        "pushed": pushed_date,
        "stars_per_day": round(stars / days_since, 1),
        "is_new": True,
        "first_seen": None,
        "stars_delta": None,
        "stars_delta_pct": None,
        "scans_seen": 0,
        "matched_projects": [],
        "matched_keywords": [],
        "category": "general",
        "reddit_validate": False,
        # Enrichment fields (Phase 2)
        "homepage": item.get("homepage", "") or "",
        "license": (item.get("license") or {}).get("spdx_id", ""),
        "archived": item.get("archived", False),
        "is_fork": item.get("fork", False),
    }


def parse_hn_hit(hit: dict) -> dict:
    """Normalize a single HN Algolia hit into our story schema."""
    object_id = str(hit.get("objectID", ""))
    points = hit.get("points", 0)
    comments = hit.get("num_comments", 0)
    controversy = round(comments / max(1, points), 2)
    divisive = controversy > CONTROVERSY_THRESHOLD

    created_unix = hit.get("created_at_i", 0)
    if created_unix:
        date_str = datetime.fromtimestamp(created_unix, tz=timezone.utc).strftime("%Y-%m-%d")
    else:
        date_str = ""

    return {
        "id": object_id,
        "title": hit.get("title", ""),
        "url": hit.get("url", "") or "",
        "hn_url": f"https://news.ycombinator.com/item?id={object_id}",
        "points": points,
        "comments": comments,
        "controversy_score": controversy,
        "divisive": divisive,
        "date": date_str,
        "matched_keywords": [],
        "category": "hn-buzz",
        "reddit_validate": divisive,
    }


# ---------------------------------------------------------------------------
# Tagging / matching
# ---------------------------------------------------------------------------

def tag_repos(repos: dict, config: dict, inv_index: tuple = None) -> None:
    """Tag each repo with matched projects, keywords, and category.

    inv_index: optional pre-built (index, broad_kws) tuple (#5).
    """
    projects = config.get("projects", {})
    interests = [i.lower() for i in config.get("interests", [])]
    if inv_index is not None:
        index, broad_kws = inv_index
    else:
        index, broad_kws = build_inverted_index(projects)

    for repo in repos.values():
        searchable_text = " ".join([
            repo.get("language") or "",
            " ".join(repo.get("topics", [])),
            repo.get("description") or "",
            repo.get("name") or "",
        ])

        matched_kws = set()
        matched_projs = set()

        for kw, proj_set in index.items():
            matched, method, score = fuzzy_match_keyword(kw, searchable_text)
            if matched:
                matched_kws.add(kw)
                if kw not in broad_kws:
                    matched_projs.update(proj_set)

        raw_topics = [t.lower() for t in repo.get("topics", [])]
        is_plugin = ".claude-plugin" in raw_topics or "claude-plugin" in raw_topics

        matched_interests = []
        for interest in interests:
            matched, method, score = fuzzy_match_keyword(interest, searchable_text)
            if matched:
                matched_interests.append(interest)

        repo["matched_projects"] = sorted(matched_projs)
        repo["matched_keywords"] = sorted(matched_kws | set(matched_interests))

        if is_plugin:
            repo["category"] = "plugin"
        elif matched_projs:
            repo["category"] = "stack-match"
        elif matched_interests:
            repo["category"] = "interest-match"
        else:
            repo["category"] = "general"


def match_hn_keywords(story: dict, config: dict, inv_index: tuple = None) -> list:
    """Match a story's title against project keywords and interests.

    inv_index: optional pre-built (index, broad_kws) tuple (#6).
    """
    title = story["title"]
    projects = config.get("projects", {})
    interests = config.get("interests", [])
    if inv_index is not None:
        index, _ = inv_index
    else:
        index, _ = build_inverted_index(projects)

    matched = set()
    for kw in index.keys():
        hit, method, score = fuzzy_match_keyword(kw, title)
        if hit:
            matched.add(kw)
    for interest in interests:
        hit, method, score = fuzzy_match_keyword(interest, title)
        if hit:
            matched.add(interest.lower())

    return sorted(matched)


def match_hn_projects(story: dict, config: dict, inv_index: tuple = None) -> list:
    """Match HN story title against project keywords.

    inv_index: optional pre-built (index, broad_kws) tuple (#6).
    """
    if inv_index is not None:
        index, broad_kws = inv_index
    else:
        index, broad_kws = build_inverted_index(config.get("projects", {}))
    title = story.get("title", "")

    matched_projs = set()
    for kw, proj_set in index.items():
        if kw in broad_kws:
            continue
        hit, method, score = fuzzy_match_keyword(kw, title)
        if hit:
            matched_projs.update(proj_set)
    return sorted(matched_projs)


def process_hn_results(raw_results: list, config: dict, inv_index: tuple = None) -> list:
    """Dedup, keyword-match, sort, cap HN results.

    inv_index: optional pre-built (index, broad_kws) tuple (#6).
    """
    # Build index once for all stories instead of per-story (#6)
    if inv_index is None:
        inv_index = build_inverted_index(config.get("projects", {}))
    seen_ids = set()
    stories = []

    for result in raw_results:
        for hit in result.get("hits", []):
            oid = str(hit.get("objectID", ""))
            if not oid or oid in seen_ids:
                continue
            seen_ids.add(oid)
            story = parse_hn_hit(hit)
            story["matched_keywords"] = match_hn_keywords(story, config, inv_index=inv_index)
            story["matched_projects"] = match_hn_projects(story, config, inv_index=inv_index)
            stories.append(story)

    stories.sort(key=lambda s: s["points"], reverse=True)
    return stories[:MAX_HN_STORIES]


def crossref_hn(under_radar: list, hn_stories: list) -> None:
    """Add hn_crossref field to under-the-radar repos whose URL or name appears in HN stories."""
    hn_url_index = {}
    for story in hn_stories:
        story_url = story.get("url", "")
        if story_url:
            hn_url_index[story_url] = story

    for repo in under_radar:
        repo_url = repo.get("url", "")
        matched_story = None

        if repo_url and repo_url in hn_url_index:
            matched_story = hn_url_index[repo_url]
        else:
            full_name = repo.get("id", "")
            if full_name:
                name_lower = full_name.lower()
                repo_name_lower = full_name.split("/", 1)[-1].lower() if "/" in full_name else name_lower
                for story in hn_stories:
                    title_lower = story.get("title", "").lower()
                    if repo_name_lower in title_lower or name_lower in title_lower:
                        matched_story = story
                        break

        if matched_story:
            repo["hn_crossref"] = {
                "title": matched_story["title"],
                "points": matched_story["points"],
                "hn_url": matched_story["hn_url"],
            }
            repo["reddit_validate"] = True


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------

def process_results(raw_results: list, config: dict, date_from: str, inv_index: tuple = None) -> tuple:
    """Dedup, tag, categorize, cap. Returns (repos_list, under_radar_list)."""
    min_stars = config.get("min_stars", 1000)

    main_items = {}
    radar_items = {}
    plugin_discovery_repos = set()

    for result in raw_results:
        query_type = result.get("query_type", "stack")
        is_plugin_query = result.get("label", "").startswith("plugin-discovery")
        for item in result.get("items", []):
            full_name = item.get("full_name", "")
            if not full_name:
                repo_info = item.get("repository", {})
                full_name = repo_info.get("full_name", "")
                if not full_name:
                    continue
                item = {
                    "full_name": full_name,
                    "description": repo_info.get("description", ""),
                    "html_url": repo_info.get("html_url", ""),
                    "stargazers_count": repo_info.get("stargazers_count", 0),
                    "language": repo_info.get("language", ""),
                    "topics": repo_info.get("topics", []),
                    "created_at": repo_info.get("created_at", ""),
                }

            if is_plugin_query:
                plugin_discovery_repos.add(full_name)

            parsed = parse_repo_item(item)
            stars = parsed["stars"]

            if query_type == "stack":
                if stars >= min_stars:
                    if full_name not in main_items:
                        main_items[full_name] = parsed
                elif stars >= 100:
                    if full_name not in radar_items:
                        radar_items[full_name] = parsed
            else:
                # Code search results may have 0 stars — filter them out
                if stars > 0 and full_name not in main_items:
                    main_items[full_name] = parsed

    tag_repos(main_items, config, inv_index=inv_index)
    tag_repos(radar_items, config, inv_index=inv_index)

    for full_name in plugin_discovery_repos:
        if full_name in main_items:
            main_items[full_name]["category"] = "plugin"

    filtered_radar = []
    for repo in radar_items.values():
        if repo["id"] in main_items:
            continue
        if repo["stars_per_day"] > 15:
            repo["reddit_validate"] = True
            filtered_radar.append(repo)
        elif repo["created"] >= date_from:
            repo["reddit_validate"] = True
            filtered_radar.append(repo)

    filtered_radar.sort(key=lambda r: r["stars_per_day"], reverse=True)
    filtered_radar = filtered_radar[:MAX_UNDER_RADAR]

    main_list = list(main_items.values())
    return main_list, filtered_radar


def process_dry_run(items: list, config: dict, date_from: str, inv_index: tuple = None) -> tuple:
    """Process fixture items the same way as live results."""
    min_stars = config.get("min_stars", 1000)

    all_items = {}
    radar_items = {}
    for item in items:
        parsed = parse_repo_item(item)
        stars = parsed["stars"]
        if stars < 100:
            continue
        if stars < min_stars:
            radar_items[parsed["id"]] = parsed
        else:
            all_items[parsed["id"]] = parsed

    tag_repos(all_items, config, inv_index=inv_index)
    tag_repos(radar_items, config, inv_index=inv_index)

    filtered_radar = []
    for repo in radar_items.values():
        if repo["stars_per_day"] > 15 or repo["created"] >= date_from:
            repo["reddit_validate"] = True
            filtered_radar.append(repo)

    filtered_radar.sort(key=lambda r: r["stars_per_day"], reverse=True)
    filtered_radar = filtered_radar[:MAX_UNDER_RADAR]

    main_list = list(all_items.values())
    return main_list, filtered_radar


# ---------------------------------------------------------------------------
# Fixture loading (for dry-run / testing)
# ---------------------------------------------------------------------------

def load_fixture(script_dir: str, name: str) -> dict:
    fixture_path = os.path.join(script_dir, "fixtures", name)
    try:
        with open(fixture_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        warn(f"Could not load fixture {name}: {exc}")
        return {}


def load_github_fixture(script_dir: str) -> list:
    data = load_fixture(script_dir, "sample-github.json")
    return data.get("items", [])


def load_hn_fixture(script_dir: str) -> list:
    data = load_fixture(script_dir, "sample-hn.json")
    return data.get("hits", [])


# ---------------------------------------------------------------------------
# Scoring & selection
# ---------------------------------------------------------------------------

def crossed_tier(stars_first: int, stars_last: int) -> bool:
    """Return True if stars crossed a tier boundary between first and last."""
    for tier in STAR_TIERS:
        if stars_first < tier <= stars_last:
            return True
    return False


def score_repos(repos: list) -> None:
    """Add relevance_score for ranking."""
    for repo in repos:
        score = 0
        cat = repo.get("category", "general")
        if cat == "stack-match":
            score += 3
        elif cat == "plugin":
            score += 2
        elif cat in ("frontend", "selfhosted", "mcp"):
            score += 1.5
        elif cat == "interest-match":
            score += 1
        if repo.get("stars_per_day", 0) > 50:
            score += 1
        repo["relevance_score"] = score


def select_diverse(repos: list, max_repos: int) -> list:
    """Select repos with category diversity guarantees."""
    buckets = {}
    for repo in repos:
        cat = repo.get("category", "general")
        buckets.setdefault(cat, []).append(repo)

    for cat in buckets:
        buckets[cat].sort(
            key=lambda r: (r.get("relevance_score", 0), r["stars"]),
            reverse=True
        )

    selected = []
    remaining_slots = max_repos
    unused_slots = 0

    for cat, allocation in sorted(DIVERSITY_SLOTS.items(), key=lambda x: -x[1]):
        available = buckets.get(cat, [])
        take = min(allocation, len(available), remaining_slots)
        selected.extend(available[:take])
        remaining_slots -= take
        unused_slots += allocation - take

    if unused_slots > 0 and remaining_slots > 0:
        already = {r["id"] for r in selected}
        overflow_priority = ["stack-match", "interest-match", "selfhosted", "frontend", "mcp", "general", "plugin"]
        for cat in overflow_priority:
            if unused_slots <= 0:
                break
            available = [r for r in buckets.get(cat, []) if r["id"] not in already]
            take = min(len(available), unused_slots, remaining_slots)
            selected.extend(available[:take])
            unused_slots -= take
            remaining_slots -= take

    selected.sort(
        key=lambda r: (r.get("relevance_score", 0), r["stars"]),
        reverse=True
    )
    return selected


def apply_post_diff_flags(repos: list, under_radar: list) -> None:
    """Set reddit_validate flags after diffing."""
    for repo in repos:
        if repo.get("stars_delta_pct") is not None and repo["stars_delta_pct"] > 100:
            repo["reddit_validate"] = True
        if repo.get("category") == "interest-match":
            repo["reddit_validate"] = True

    for repo in under_radar:
        if repo.get("stars_delta_pct") is not None and repo["stars_delta_pct"] > 100:
            repo["reddit_validate"] = True
        if repo.get("category") == "interest-match":
            repo["reddit_validate"] = True


# ---------------------------------------------------------------------------
# DB diff logic (replaces history.json-based diff_repos)
# ---------------------------------------------------------------------------

def diff_repos_db(db, repos: list, today: str) -> dict:
    """Apply DB-based diffing to repos. Returns counts dict.

    Batch-fetches all existing repos, annotations, and latest snapshots
    in 3 bulk queries upfront (#4), then does dict lookups in the loop.
    """
    new_count = 0
    returning_count = 0
    rising_count = 0
    skipped_rejected = 0

    # Batch-fetch all data upfront (#4: 3 queries instead of ~90)
    full_names = [r["id"] for r in repos]
    if not full_names:
        return {"new": 0, "returning": 0, "rising": 0, "skipped_rejected": 0}

    placeholders = ",".join("?" * len(full_names))

    # 1. Bulk fetch repos by full_name
    repo_rows = db.execute(
        f"SELECT id, full_name, first_seen FROM repos WHERE full_name IN ({placeholders})",
        full_names
    ).fetchall()
    existing_repos = {row[1]: {"id": row[0], "first_seen": row[2]} for row in repo_rows}

    # 2. Bulk fetch annotation statuses for existing repo IDs
    repo_ids = [r["id"] for r in existing_repos.values()]
    annotation_map = {}
    if repo_ids:
        id_placeholders = ",".join("?" * len(repo_ids))
        ann_rows = db.execute(
            f"SELECT repo_id, status FROM annotations WHERE repo_id IN ({id_placeholders})",
            repo_ids
        ).fetchall()
        annotation_map = {row[0]: row[1] for row in ann_rows}

    # 3. Bulk fetch latest star counts for existing repo IDs
    prev_stars_map = {}
    if repo_ids:
        star_rows = db.execute(f"""
            SELECT ss.repo_id, ss.stars
            FROM scan_snapshots ss
            INNER JOIN (
                SELECT repo_id, MAX(scan_id) as max_scan_id
                FROM scan_snapshots
                WHERE repo_id IN ({id_placeholders})
                GROUP BY repo_id
            ) latest ON ss.repo_id = latest.repo_id AND ss.scan_id = latest.max_scan_id
        """, repo_ids).fetchall()
        prev_stars_map = {row[0]: row[1] for row in star_rows}

    filtered_repos = []
    for repo in repos:
        full_name = repo["id"]
        existing = existing_repos.get(full_name)

        # Check annotation status
        if existing:
            annotation_status = annotation_map.get(existing["id"])
            if annotation_status == "rejected":
                skipped_rejected += 1
                continue  # skip rejected repos entirely

        if existing:
            repo["is_new"] = False
            repo["first_seen"] = existing.get("first_seen")

            # Get previous stars from pre-fetched map
            prev_stars = prev_stars_map.get(existing["id"])
            if prev_stars is not None:
                stars = repo.get("stars", 0)
                stars_delta = stars - prev_stars
                stars_delta_pct = round((stars_delta / max(1, prev_stars)) * 100, 1)
                repo["stars_delta"] = stars_delta
                repo["stars_delta_pct"] = stars_delta_pct

                # Rising star detection
                is_rising = (stars_delta_pct > 20) or crossed_tier(prev_stars, stars)
                repo["is_rising"] = is_rising
                if is_rising:
                    rising_count += 1
            else:
                repo["stars_delta"] = None
                repo["stars_delta_pct"] = None
                repo["is_rising"] = False

            returning_count += 1
        else:
            repo["is_new"] = True
            repo["first_seen"] = today
            repo["stars_delta"] = None
            repo["stars_delta_pct"] = None
            repo["is_rising"] = False
            new_count += 1

        filtered_repos.append(repo)

    # Replace the list contents in-place
    repos.clear()
    repos.extend(filtered_repos)

    return {
        "new": new_count,
        "returning": returning_count,
        "rising": rising_count,
        "skipped_rejected": skipped_rejected,
    }


# ---------------------------------------------------------------------------
# Write to DB (replaces build_output)
# ---------------------------------------------------------------------------

def write_to_db(db, scan_id, repos, under_radar, hn_stories):
    """Write gather results to SQLite. Replaces build_output().

    For each repo:
    - Upsert into repos table (by full_name)
    - Insert a scan_snapshot with computed fields
    - Call compute_needs_verdict() to set the needs_verdict flag

    For under_radar repos: same flow but with is_under_radar=1.

    HN context is stored as text on scan_snapshots for repos that have
    cross-references (per decision D4).
    """
    def _write_repo(repo, is_under_radar=False):
        full_name = repo["id"]
        stars = repo.get("stars", 0)

        # Build repo data for upsert
        repo_data = {
            "full_name": full_name,
            "owner": repo.get("owner", ""),
            "repo_name": repo.get("name", ""),
            "description": repo.get("description", ""),
            "language": repo.get("language", ""),
            "topics": repo.get("topics", []),
            "url": repo.get("url", ""),
            "homepage": repo.get("homepage", ""),
            "license": repo.get("license", ""),
            "archived": 1 if repo.get("archived") else 0,
            "is_fork": 1 if repo.get("is_fork") else 0,
            "created_at": repo.get("created", ""),
            "pushed_at": repo.get("pushed", ""),
        }

        repo_row = db_module.upsert_repo(db, repo_data)
        repo_id = repo_row["id"]

        # Build HN context string from crossref if present
        hn_context = ""
        hn_crossref = repo.get("hn_crossref")
        if hn_crossref:
            title = hn_crossref.get("title", "")
            points = hn_crossref.get("points", 0)
            hn_context = f"HN: '{title}' ({points} pts)"

        # Compute needs_verdict
        needs_verdict = db_module.compute_needs_verdict(db, repo_id, stars)

        # Insert snapshot
        snapshot = {
            "repo_id": repo_id,
            "scan_id": scan_id,
            "stars": stars,
            "stars_delta": repo.get("stars_delta"),
            "stars_delta_pct": repo.get("stars_delta_pct"),
            "stars_per_day": repo.get("stars_per_day"),
            "category": repo.get("category", "general"),
            "is_under_radar": 1 if is_under_radar else 0,
            "is_rising": 1 if repo.get("is_rising") else 0,
            "relevance_score": repo.get("relevance_score"),
            "matched_keywords": repo.get("matched_keywords", []),
            "matched_projects": repo.get("matched_projects", []),
            "reddit_validate": 1 if repo.get("reddit_validate") else 0,
            "hn_context": hn_context,
            "needs_verdict": 1 if needs_verdict else 0,
        }
        db_module.insert_snapshot(db, snapshot)

    # Transaction: atomic writes + batched WAL flushes (#1)
    with db.conn:
        # Write main repos
        for repo in repos:
            _write_repo(repo, is_under_radar=False)

        # Write under-the-radar repos
        for repo in under_radar:
            _write_repo(repo, is_under_radar=True)


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def run_gather(timeframe="monthly", source="all", max_repos=None,
               dry_run=False, show_queries=False, no_fuzzy=False,
               db_path=None, config_path="~/.tech-radar.json"):
    """Orchestrate the full gather pipeline.

    1. Load config
    2. Resolve GitHub token
    3. Build queries
    4. Fetch from GitHub + HN (concurrent)
    5. Parse, tag, score, select diverse
    6. Open DB, create scan entry, write results via write_to_db()
    7. Return summary stats
    """
    # Temporarily disable rapidfuzz if requested, restore on exit (#9)
    import tech_radar.normalize as norm_module
    _orig_rapidfuzz = norm_module.HAS_RAPIDFUZZ
    if no_fuzzy:
        norm_module.HAS_RAPIDFUZZ = False

    try:
        return _run_gather_inner(
            timeframe=timeframe, source=source, max_repos=max_repos,
            dry_run=dry_run, show_queries=show_queries, db_path=db_path,
            config_path=config_path,
        )
    finally:
        norm_module.HAS_RAPIDFUZZ = _orig_rapidfuzz


def _run_gather_inner(*, timeframe, source, max_repos, dry_run, show_queries,
                      db_path, config_path):
    """Inner gather logic, called by run_gather with fuzzy state protected."""
    max_repos = max_repos or MAX_RESULTS

    # Load config
    config = load_config(config_path)
    min_stars = config.get("min_stars", 1000)

    # Date range
    date_from, date_to = date_range(timeframe)
    since_unix = date_to_unix(date_from)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # --show-queries: print and return
    if show_queries:
        queries = build_queries(config)
        hn_kws = build_hn_keywords(config)
        print("GitHub queries:", file=sys.stderr)
        for label, q_kw, stype, qtype in queries:
            print(f"  [{qtype}/{stype}] {label}", file=sys.stderr)
            print(f"    q={q_kw}", file=sys.stderr)
        print(f"\n  Total: {len(queries)} queries", file=sys.stderr)
        print(f"\nHN keywords: {len(hn_kws)}", file=sys.stderr)
        for label, kw in hn_kws:
            print(f"  {label}: {kw}", file=sys.stderr)
        return {"status": "show-queries", "github_queries": len(queries), "hn_queries": len(hn_kws)}

    # Source flags
    run_github = source in ("github", "all")
    run_hn = source in ("hn", "all")

    # Build inverted index once, pass through all functions (#5/#6)
    inv_index = build_inverted_index(config.get("projects", {}))

    # Script directory (for fixtures)
    script_dir = os.path.dirname(os.path.abspath(__file__))
    # Fixtures are in the parent scripts/ directory
    scripts_dir = os.path.dirname(script_dir)

    # Collect data
    repos = []
    under_radar = []
    hn_stories = []
    github_query_count = 0
    github_total_raw = 0
    github_error = None
    hn_query_count = 0
    hn_total_raw = 0
    hn_error = None

    start_time = time.time()

    if dry_run:
        warn("Dry-run mode: reading from fixtures")
        if run_github:
            gh_items = load_github_fixture(scripts_dir)
            repos, under_radar = process_dry_run(gh_items, config, date_from, inv_index=inv_index)
            github_total_raw = len(gh_items)

        if run_hn:
            hn_hits = load_hn_fixture(scripts_dir)
            raw_hn = [{"hits": hn_hits}]
            hn_stories = process_hn_results(raw_hn, config, inv_index=inv_index)
            hn_query_count = 1
            hn_total_raw = len(hn_hits)
    else:
        queries = build_queries(config) if run_github else []
        hn_keywords = build_hn_keywords(config) if run_hn else []
        token = resolve_github_token() if run_github else None

        if run_github:
            warn(f"Generated {len(queries)} GitHub queries for timeframe={timeframe}")
        if run_hn:
            warn(f"Generated {len(hn_keywords)} HN queries")

        if run_github and run_hn:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                gh_future = pool.submit(fetch_all_github, queries, date_from, min_stars, token)
                hn_future = pool.submit(fetch_all_hn, hn_keywords, since_unix)
                raw_results, github_error = gh_future.result()
                raw_hn_results, hn_error = hn_future.result()
            github_total_raw = sum(len(r.get("items", [])) for r in raw_results)
            github_query_count = len(raw_results)
            repos, under_radar = process_results(raw_results, config, date_from, inv_index=inv_index)
            hn_total_raw = sum(len(r.get("hits", [])) for r in raw_hn_results)
            hn_query_count = len(raw_hn_results)
            hn_stories = process_hn_results(raw_hn_results, config, inv_index=inv_index)
        else:
            if run_github:
                raw_results, github_error = fetch_all_github(queries, date_from, min_stars, token)
                github_total_raw = sum(len(r.get("items", [])) for r in raw_results)
                github_query_count = len(raw_results)
                repos, under_radar = process_results(raw_results, config, date_from, inv_index=inv_index)

            if run_hn:
                raw_hn_results, hn_error = fetch_all_hn(hn_keywords, since_unix)
                hn_total_raw = sum(len(r.get("hits", [])) for r in raw_hn_results)
                hn_query_count = len(raw_hn_results)
                hn_stories = process_hn_results(raw_hn_results, config, inv_index=inv_index)

    # HN cross-reference — enrich all repos, not just under-radar
    if run_github and run_hn and hn_stories:
        crossref_hn(repos, hn_stories)
        crossref_hn(under_radar, hn_stories)

    # Open DB and diff against it
    db = db_module.open_db(db_path)

    # ------------------------------------------------------------------
    # External sources: verticals (awesome lists, topics, seed repos)
    # ------------------------------------------------------------------
    verticals = config.get("verticals", {})
    vertical_repo_count = 0
    if verticals and not dry_run and run_github:
        vertical_results = sources_module.fetch_all_verticals(
            config, token, date_from, db
        )
        existing_ids = {r["id"] for r in repos}
        for vert_name, vert_items in vertical_results.items():
            for item in vert_items:
                full_name = item.get("full_name", "")
                if not full_name or full_name in existing_ids:
                    continue
                parsed = parse_repo_item(item)
                parsed["category"] = vert_name  # Set vertical category
                repos.append(parsed)
                existing_ids.add(full_name)
                vertical_repo_count += 1

        if vertical_repo_count:
            warn(f"Added {vertical_repo_count} repos from external sources")
            # Re-tag: tag_repos may promote to stack-match if keywords match
            # Preserve vertical and plugin categories for repos that don't get a stronger match
            preserve_cats = set(verticals.keys()) | {"plugin"}
            prev_cats = {r["id"]: r["category"] for r in repos if r["category"] in preserve_cats}
            repos_dict = {r["id"]: r for r in repos}
            tag_repos(repos_dict, config, inv_index=inv_index)
            # Restore vertical category for repos that fell through to "general"
            for rid, repo in repos_dict.items():
                if repo["category"] == "general" and rid in prev_cats:
                    repo["category"] = prev_cats[rid]
            repos = list(repos_dict.values())

    repo_counts = diff_repos_db(db, repos, today)
    utr_counts = diff_repos_db(db, under_radar, today)

    combined_counts = {
        "new": repo_counts["new"] + utr_counts["new"],
        "returning": repo_counts["returning"] + utr_counts["returning"],
        "rising": repo_counts["rising"] + utr_counts["rising"],
        "skipped_rejected": repo_counts["skipped_rejected"] + utr_counts["skipped_rejected"],
    }

    # Post-diff flag updates
    apply_post_diff_flags(repos, under_radar)

    # Relevance scoring and diversity selection
    score_repos(repos)
    full_repos = list(repos)
    repos = select_diverse(repos, max_repos)

    # Per-project minimum: ensure registered projects have coverage (#10/#11)
    registered = set(config.get("projects", {}).keys())
    covered = {p for r in repos for p in r.get("matched_projects", [])}
    uncovered = registered - covered

    if uncovered and full_repos:
        selected_ids = {x["id"] for x in repos}  # Build once (#11)
        for proj in sorted(uncovered):
            candidates = [r for r in full_repos
                          if proj in r.get("matched_projects", [])
                          and r["id"] not in selected_ids]
            if candidates:
                candidates.sort(key=lambda r: r["stars"], reverse=True)
                best = candidates[0]
                # Find largest category and displace its weakest member
                cat_counts = {}
                for r in repos:
                    c = r.get("category", "general")
                    cat_counts[c] = cat_counts.get(c, 0) + 1
                if cat_counts:
                    largest_cat = max(cat_counts, key=cat_counts.get)
                    cat_repos = [(i, r) for i, r in enumerate(repos)
                                 if r.get("category") == largest_cat]
                    cat_repos.sort(key=lambda x: (x[1].get("relevance_score", 0), x[1]["stars"]))
                    if cat_repos:
                        removed = repos.pop(cat_repos[0][0])
                        selected_ids.discard(removed["id"])
                        repos.append(best)
                        selected_ids.add(best["id"])

    duration = round(time.time() - start_time, 1)

    # Create scan record
    scan_data = {
        "scan_date": today,
        "timeframe": timeframe,
        "github_queries": github_query_count,
        "hn_queries": hn_query_count,
        "repos_found": len(repos) + len(under_radar),
        "repos_new": combined_counts["new"],
        "repos_returning": combined_counts["returning"],
        "repos_rising": combined_counts["rising"],
        "duration_seconds": duration,
        "metadata": json.dumps({
            "source": source,
            "github_total_raw": github_total_raw,
            "hn_total_raw": hn_total_raw,
            "github_error": github_error,
            "hn_error": hn_error,
            "dry_run": dry_run,
            "skipped_rejected": combined_counts["skipped_rejected"],
            "vertical_repos": vertical_repo_count,
        }),
    }
    scan_id = db_module.insert_scan(db, scan_data)

    # Write results to DB
    write_to_db(db, scan_id, repos, under_radar, hn_stories)

    summary = {
        "status": "ok",
        "scan_id": scan_id,
        "timeframe": timeframe,
        "date_range": {"from": date_from, "to": date_to},
        "repos_selected": len(repos),
        "under_radar": len(under_radar),
        "hn_stories": len(hn_stories),
        "new": combined_counts["new"],
        "returning": combined_counts["returning"],
        "rising": combined_counts["rising"],
        "skipped_rejected": combined_counts["skipped_rejected"],
        "github_queries": github_query_count,
        "hn_queries": hn_query_count,
        "duration_seconds": duration,
        "dry_run": dry_run,
    }

    warn(f"Scan complete: {len(repos)} repos selected, "
         f"{len(under_radar)} under-radar, {len(hn_stories)} HN stories, "
         f"{combined_counts['new']} new, {combined_counts['returning']} returning, "
         f"{combined_counts['rising']} rising "
         f"({duration}s)")

    return summary
