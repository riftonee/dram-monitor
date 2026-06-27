"""Collect: pull news from all sources and normalize to a common item shape.

Each item is normalized to:
    {id, source, topic, title, url, published_at, published_ts, snippet}
`id` is a stable hash used for dedupe (state/seen.json), so it must derive from
content that doesn't change between runs. `published_ts` is epoch seconds (UTC)
or None, used by the recency filter.

Sources:
  - Google News RSS    (no key; the workhorse, also covers the Korean holdings)
  - Finnhub            (FINNHUB_KEY; US-ticker company news, every cycle)
  - SEC EDGAR          (no key; 8-K filings for US holdings)
  - Alpha Vantage      (ALPHA_VANTAGE_KEY; rate-limited — daily collection only)

Every fetcher is defensive: a source that errors logs to stderr and contributes
nothing rather than aborting the run.

Run:  python3 -m src.collect
"""

from __future__ import annotations

import calendar
import email.utils
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request

import feedparser

import config

_HTTP_TIMEOUT = 15
_USER_AGENT = "dram-monitor/1.0"


def _make_id(url: str, title: str, source: str) -> str:
    """Stable dedupe id. Prefer the URL; fall back to title+source (BRIEF.md)."""
    basis = url.strip() if url else f"{title}|{source}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def _item(*, source, topic, title, url, published_ts, published_at, snippet) -> dict:
    """Build one normalized item with its stable dedupe id."""
    return {
        "id": _make_id(url, title, source),
        "source": source,
        "topic": topic,
        "title": title.strip(),
        "url": url.strip(),
        "published_at": published_at,
        "published_ts": published_ts,
        "snippet": (snippet or "").strip(),
    }


def _fetch_json(url: str) -> dict | list:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as response:
        return json.load(response)


# --- Google News RSS -------------------------------------------------------


def _published_ts(entry) -> float | None:
    """Epoch seconds (UTC) for a feedparser entry, or None if unparseable."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return calendar.timegm(parsed)
    # feedparser sometimes fails to parse valid RFC 2822 strings; try stdlib as a fallback.
    raw = entry.get("published") or entry.get("updated")
    if raw:
        tup = email.utils.parsedate(raw)
        if tup:
            return calendar.timegm(tup)
    return None


def _google_news_url(query: str) -> str:
    params = {"q": query, **config.GOOGLE_NEWS_PARAMS}
    return f"{config.GOOGLE_NEWS_RSS}?{urllib.parse.urlencode(params)}"


def collect_google_news() -> list[dict]:
    items: list[dict] = []
    for topic, query in config.GOOGLE_NEWS_QUERIES:
        feed = feedparser.parse(_google_news_url(query))
        if feed.bozo:
            print(f"  ! google news error for {query!r}: {feed.bozo_exception}", file=sys.stderr)
        for entry in feed.entries:
            source = getattr(getattr(entry, "source", None), "title", "Google News")
            items.append(
                _item(
                    source=source,
                    topic=topic,
                    title=entry.get("title", ""),
                    url=entry.get("link", ""),
                    published_ts=_published_ts(entry),
                    published_at=entry.get("published", ""),
                    snippet=entry.get("summary", ""),
                )
            )
    return items


# --- Finnhub ---------------------------------------------------------------


def collect_finnhub() -> list[dict]:
    key = os.environ.get("FINNHUB_KEY")
    if not key:
        return []
    today = time.gmtime()
    to_date = time.strftime("%Y-%m-%d", today)
    from_date = time.strftime("%Y-%m-%d", time.gmtime(time.time() - config.FINNHUB_LOOKBACK_DAYS * 86400))
    items: list[dict] = []
    for ticker in config.US_TICKERS:
        params = {"symbol": ticker, "from": from_date, "to": to_date, "token": key}
        url = f"{config.FINNHUB_ENDPOINT}?{urllib.parse.urlencode(params)}"
        try:
            rows = _fetch_json(url)
        except Exception as error:  # noqa: BLE001 — defensive: one source must not kill the run
            print(f"  ! finnhub error for {ticker}: {error}", file=sys.stderr)
            continue
        for row in rows or []:
            items.append(
                _item(
                    source=f"Finnhub/{row.get('source', '?')}",
                    topic="holding",
                    title=row.get("headline", ""),
                    url=row.get("url", ""),
                    published_ts=float(row["datetime"]) if row.get("datetime") else None,
                    published_at=time.strftime("%Y-%m-%d", time.gmtime(row["datetime"])) if row.get("datetime") else "",
                    snippet=row.get("summary", ""),
                )
            )
    return items


# --- SEC EDGAR -------------------------------------------------------------


def _edgar_get(url: str) -> dict | list:
    # data.sec.gov requires a descriptive UA with a contact; honor the env value.
    ua = os.environ.get("EDGAR_USER_AGENT") or _USER_AGENT
    request = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(request, timeout=_HTTP_TIMEOUT) as response:
        return json.load(response)


_edgar_cik_cache: dict[str, str] | None = None


def _edgar_cik_map() -> dict[str, str]:
    """Map ticker -> zero-padded 10-digit CIK from SEC's published index (cached)."""
    global _edgar_cik_cache
    if _edgar_cik_cache is None:
        data = _edgar_get("https://www.sec.gov/files/company_tickers.json")
        _edgar_cik_cache = {
            row["ticker"].upper(): f"{int(row['cik_str']):010d}" for row in data.values()
        }
    return _edgar_cik_cache


def collect_edgar() -> list[dict]:
    """Recent 8-K filings for the US holdings via SEC's submissions JSON API."""
    try:
        cik_map = _edgar_cik_map()
    except Exception as error:  # noqa: BLE001 — defensive
        print(f"  ! edgar cik map error: {error}", file=sys.stderr)
        return []

    wanted = {t.upper() for t in config.EDGAR_FILING_TYPES}
    items: list[dict] = []
    for ticker in config.US_TICKERS:
        cik = cik_map.get(ticker.upper())
        if not cik:
            continue
        try:
            data = _edgar_get(f"https://data.sec.gov/submissions/CIK{cik}.json")
        except Exception as error:  # noqa: BLE001 — defensive
            print(f"  ! edgar error for {ticker}: {error}", file=sys.stderr)
            continue
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        docs = recent.get("primaryDocument", [])
        descs = recent.get("primaryDocDescription", [])
        count = 0
        for i, form in enumerate(forms):
            if form not in wanted:
                continue
            if count >= config.EDGAR_ITEMS_PER_TICKER:
                break
            count += 1
            date = dates[i] if i < len(dates) else ""
            accession_nodash = accessions[i].replace("-", "") if i < len(accessions) else ""
            doc = docs[i] if i < len(docs) else ""
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_nodash}/{doc}"
                if accession_nodash
                else ""
            )
            try:
                published_ts = calendar.timegm(time.strptime(date, "%Y-%m-%d")) if date else None
            except ValueError:
                published_ts = None
            items.append(
                _item(
                    source=f"SEC EDGAR ({ticker})",
                    topic="holding",
                    title=f"{ticker} {form} filed {date}",
                    url=url,
                    published_ts=published_ts,
                    published_at=date,
                    snippet=descs[i] if i < len(descs) else "",
                )
            )
    return items


# --- Alpha Vantage (rate-limited: daily collection only) -------------------


def collect_alpha_vantage() -> list[dict]:
    key = os.environ.get("ALPHA_VANTAGE_KEY")
    if not key:
        return []
    items: list[dict] = []
    # Server-side recency filter: AV has no default cutoff so it returns historical stories.
    time_from = time.strftime("%Y%m%dT%H%M", time.gmtime(time.time() - config.MAX_ITEM_AGE_HOURS * 3600))
    for ticker in config.US_TICKERS:
        params = {
            "function": "NEWS_SENTIMENT",
            "tickers": ticker,
            "limit": config.ALPHA_VANTAGE_ITEMS_PER_TICKER,
            "time_from": time_from,
            "apikey": key,
        }
        url = f"{config.ALPHA_VANTAGE_ENDPOINT}?{urllib.parse.urlencode(params)}"
        try:
            data = _fetch_json(url)
        except Exception as error:  # noqa: BLE001 — defensive
            print(f"  ! alpha vantage error for {ticker}: {error}", file=sys.stderr)
            continue
        if not isinstance(data, dict) or "feed" not in data:
            # AV returns {"Note"/"Information": ...} when rate-limited.
            note = (data or {}).get("Note") or (data or {}).get("Information")
            if note:
                print(f"  ! alpha vantage limited for {ticker}: {note}", file=sys.stderr)
            continue
        for row in data["feed"]:
            stamp = row.get("time_published", "")  # format: 20260608T153000
            try:
                published_ts = calendar.timegm(time.strptime(stamp, "%Y%m%dT%H%M%S"))
            except ValueError:
                published_ts = None
            items.append(
                _item(
                    source=f"AlphaVantage/{row.get('source', '?')}",
                    topic="holding",
                    title=row.get("title", ""),
                    url=row.get("url", ""),
                    published_ts=published_ts,
                    published_at=stamp,
                    snippet=row.get("summary", ""),
                )
            )
    return items


# --- Aggregate -------------------------------------------------------------


def collect_all(include_rate_limited: bool = False) -> list[dict]:
    """All sources. `include_rate_limited` adds Alpha Vantage — pass True only on
    the once-daily collection (its free tier is ~25 requests/day)."""
    items = collect_google_news()
    items += collect_finnhub()
    items += collect_edgar()
    if include_rate_limited:
        items += collect_alpha_vantage()
    return items


def main() -> None:
    items = collect_all(include_rate_limited="--all" in sys.argv[1:])
    by_source: dict[str, int] = {}
    for item in items:
        key = item["source"].split("/")[0].split(" (")[0]
        by_source[key] = by_source.get(key, 0) + 1
    for item in items:
        print(f"[{item['topic']:>8}] {item['title'][:80]}")
    print(f"\n--- collected {len(items)} items ---")
    for src, n in sorted(by_source.items(), key=lambda kv: -kv[1]):
        print(f"    {n:>4}  {src}")


if __name__ == "__main__":
    main()
