"""Collect: pull news from all sources and normalize to a common item shape.

Milestone 1 covers Google News RSS only. Each item is normalized to:
    {id, source, topic, title, url, published_at, snippet}
`id` is a stable hash used for dedupe in a later milestone (state/seen.json), so it
must be derived from content that does not change between runs.

Run:  python3 -m src.collect
"""

from __future__ import annotations

import calendar
import hashlib
import sys
import urllib.parse

import feedparser

import config


def _make_id(url: str, title: str, source: str) -> str:
    """Stable dedupe id. Prefer the URL; fall back to title+source (BRIEF.md)."""
    basis = url.strip() if url else f"{title}|{source}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def _published_ts(entry) -> float | None:
    """Epoch seconds (UTC) for the entry, or None if unparseable.

    feedparser exposes `published_parsed` as a UTC time.struct_time; calendar.timegm
    converts it without dragging in the local timezone (time.mktime would).
    """
    parsed = entry.get("published_parsed")
    return calendar.timegm(parsed) if parsed else None


def _google_news_url(query: str) -> str:
    params = {"q": query, **config.GOOGLE_NEWS_PARAMS}
    return f"{config.GOOGLE_NEWS_RSS}?{urllib.parse.urlencode(params)}"


def collect_google_news() -> list[dict]:
    """Fetch every configured Google News query and return normalized items."""
    items: list[dict] = []
    for topic, query in config.GOOGLE_NEWS_QUERIES:
        feed = feedparser.parse(_google_news_url(query))
        if feed.bozo:
            print(f"  ! feed error for {query!r}: {feed.bozo_exception}", file=sys.stderr)
        for entry in feed.entries:
            # Google News tags the originating outlet in entry.source.title.
            source = getattr(getattr(entry, "source", None), "title", "Google News")
            title = entry.get("title", "").strip()
            url = entry.get("link", "").strip()
            items.append(
                {
                    "id": _make_id(url, title, source),
                    "source": source,
                    "topic": topic,
                    "title": title,
                    "url": url,
                    "published_at": entry.get("published", ""),
                    "published_ts": _published_ts(entry),
                    "snippet": entry.get("summary", "").strip(),
                }
            )
    return items


def collect_all() -> list[dict]:
    """All sources. Milestone 1: Google News RSS only."""
    return collect_google_news()


def main() -> None:
    items = collect_all()
    for item in items:
        print(f"[{item['topic']:>8}] {item['title']}")
        print(f"           {item['source']} — {item['published_at']}")
        print(f"           {item['url']}")
        print()
    print(f"--- collected {len(items)} items from {len(config.GOOGLE_NEWS_QUERIES)} queries ---")


if __name__ == "__main__":
    main()
