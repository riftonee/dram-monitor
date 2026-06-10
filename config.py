"""Watchlist, source queries, and thresholds for the DRAM monitor.

This is the single place to tune what gets watched. See BRIEF.md for the rationale
behind each list. Golden rule: never search the bare word "DRAM" — scope by ticker
or by a curated topic query, or you flood with memory-technology trivia.
"""

# US-listed holdings that appear cleanly in ticker news APIs (used from Milestone 6).
US_TICKERS = ["MU", "SNDK", "STX", "WDC"]

# Korean holdings — these do NOT show up in US ticker APIs, so they are covered
# only via the topic queries below (Google News RSS + Reuters/Yonhap).
#   SK hynix   KRX:000660  (largest position)
#   Samsung    KRX:005930

# Google News RSS topic queries. Each becomes one feed.
# (label, query) — the label is the `topic` we tag collected items with.
GOOGLE_NEWS_QUERIES = [
    # Holdings by name (covers the Korean names US ticker APIs miss)
    ("holding", "Micron guidance"),
    ("holding", "SK Hynix"),
    ("holding", "Samsung memory"),
    ("holding", "Western Digital memory"),
    ("holding", "Seagate"),
    ("holding", "SanDisk"),
    # Industry / theme — the leading indicators
    ("industry", "HBM demand"),
    ("industry", "memory chip shortage"),
    ("industry", "DRAM production cut"),
    # Pricing — memory is a commodity cycle; pricing often moves stocks before earnings
    ("pricing", "DRAM contract price"),
    ("pricing", "NAND prices"),
    ("pricing", "TrendForce DRAM"),
    # Fund-level
    ("fund", "Roundhill Memory ETF DRAM"),
]

# Google News RSS endpoint settings.
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
GOOGLE_NEWS_PARAMS = {"hl": "en-US", "gl": "US", "ceid": "US:en"}

# --- Ticker-API sources (US holdings only; the Korean names are covered by the
# Google News queries above, since they don't appear cleanly in US ticker APIs) ---

# Alpha Vantage NEWS_SENTIMENT. Free tier is ~25 requests/DAY, so this source is
# rate-limited: it runs only on the once-daily collection, never every 30 min.
# Needs ALPHA_VANTAGE_KEY.
ALPHA_VANTAGE_ENDPOINT = "https://www.alphavantage.co/query"
ALPHA_VANTAGE_ITEMS_PER_TICKER = 10

# Finnhub company-news. Free tier ~60 req/min — fine to run every cycle.
# Needs FINNHUB_KEY.
FINNHUB_ENDPOINT = "https://finnhub.io/api/v1/company-news"
FINNHUB_LOOKBACK_DAYS = 2

# SEC EDGAR filings (free, no key) via the submissions JSON API. SEC asks for a
# descriptive User-Agent with a contact; set EDGAR_USER_AGENT in the env (kept
# out of the public repo) rather than hardcoding a personal email here.
EDGAR_FILING_TYPES = ["8-K"]  # material events / earnings; most signal-dense
EDGAR_ITEMS_PER_TICKER = 5

# Recency: ignore anything older than this. Combined with dedupe, this keeps the
# very first run from importing a months-deep backlog, and bounds steady-state work.
MAX_ITEM_AGE_HOURS = 48

# How long an id stays in state/seen.json before it is pruned. Must comfortably
# exceed MAX_ITEM_AGE_HOURS so a still-recent story can never be re-imported.
SEEN_RETENTION_DAYS = 30

# Routing thresholds (used from Milestone 4).
INSTANT_ALERT_IMPACT = 4  # impact >= this triggers an instant alert email
