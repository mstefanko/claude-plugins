"""Module-level constants shared across tech_radar modules."""

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

GITHUB_SEARCH_REPOS = "https://api.github.com/search/repositories"
GITHUB_SEARCH_CODE = "https://api.github.com/search/code"
HN_ALGOLIA_SEARCH = "https://hn.algolia.com/api/v1/search"

# ---------------------------------------------------------------------------
# Scan parameters
# ---------------------------------------------------------------------------

TIMEFRAME_DAYS = {"weekly": 7, "monthly": 30, "quarterly": 90}
MAX_RESULTS = 20
MAX_UNDER_RADAR = 5
MAX_HN_STORIES = 15
HN_MIN_POINTS = 50
CONTROVERSY_THRESHOLD = 1.5

# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

UNAUTHENTICATED_MAX_QUERIES = 4
UNAUTHENTICATED_DELAY = 6  # seconds between sequential calls
THREAD_POOL_SIZE = 4
RATE_LIMIT_BATCH_SIZE = 25       # max queries before pausing (GitHub allows 30/min)
RATE_LIMIT_BATCH_PAUSE = 60      # seconds to wait between batches
PER_REQUEST_DELAY = 0.1          # seconds between individual requests in thread pool

# ---------------------------------------------------------------------------
# Keyword / matching
# ---------------------------------------------------------------------------

BROAD_KEYWORD_THRESHOLD = 3  # Keywords in N+ projects are "broad"

SYNONYMS = {
    "claude-code": ["claude code", "claudecode", "claude cli"],
    "rails": ["ruby on rails", "rubyonrails", "ror"],
    "stimulus": ["stimulusjs", "stimulus js", "hotwire stimulus"],
    "turbo": ["turbo rails", "hotwire turbo"],
    "hotwire": ["hotwire rails"],
    "react": ["reactjs", "react js"],
    "nextjs": ["next.js", "next js"],
    "docker": ["containerization", "dockerfile"],
    "kubernetes": ["k8s", "kube"],
    "playwright": ["playwright test"],
    "mysql": ["mariadb"],
    "sqlite": ["sqlite3"],
    "typescript": ["typescript language"],
    "obsidian": ["obsidian md", "obsidian plugin", "obsidian vault"],
    "figma": ["figma plugin", "figma design"],
    "hipaa": ["hipaa compliance"],
    "healthcare": ["health tech", "healthtech", "medtech"],
    "dme": ["durable medical equipment"],
    "orthopedics": ["ortho", "orthopedic"],
    "bootstrap": ["bootstrap css"],
    "rspec": ["rspec test"],
}

# ---------------------------------------------------------------------------
# Selection / diversity
# ---------------------------------------------------------------------------

DIVERSITY_SLOTS = {
    "stack-match": 12,
    "interest-match": 3,
    "general": 3,
    "plugin": 2,
}

# Star tier boundaries for rising-star detection
STAR_TIERS = [1000, 5000, 20000]

# Keywords that should be skipped by the "too-specific" heuristic even if
# they appear for only one project.
SKIP_TESTING_TOOLS = frozenset([
    "factory_bot", "cucumber", "rspec", "minitest", "capybara",
    "shoulda", "vcr", "webmock", "faker", "simplecov",
])

# Primary language/framework keywords that should never be skipped.
PRIMARY_KEYWORDS = frozenset([
    "ruby", "rails", "python", "node", "typescript", "javascript",
    "go", "rust", "java", "elixir", "bash", "sqlite", "mysql",
    "postgres", "redis", "docker", "react", "vue", "angular",
    "stimulus", "turbo", "hotwire", "playwright", "markdown",
    "esbuild", "webpack", "sidekiq", "puma",
])

# ---------------------------------------------------------------------------
# Version detection
# ---------------------------------------------------------------------------

_VERSION_CHARS = set("0123456789.")

# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

HISTORY_VERSION = 1
