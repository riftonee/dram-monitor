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

# Routing thresholds (used from Milestone 4).
INSTANT_ALERT_IMPACT = 4  # impact >= this triggers an instant alert email
