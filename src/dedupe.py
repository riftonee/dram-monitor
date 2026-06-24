"""Same-story dedupe: collapse near-identical items about a single event.

Many outlets cover one event (e.g. a single Micron earnings report -> 7 near-
identical headlines). The exact-URL dedup in seen.json deliberately can't catch
these; this is a separate SEMANTIC layer. It runs BEFORE triage on a run's new
items (so one event costs one triage call instead of one per outlet) and AGAIN
over the whole buffer before the brief (see CLAUDE.md).

It clusters items by normalized-title similarity, keeps one item as the cluster
representative (`_rep_rank`: highest triage impact when scored, else most outlets
then longest title), and records how many outlets corroborated it under a
`corroboration` key so the alert digest and the brief can say "(N outlets)".

No AI call — this is deterministic text similarity, so it adds zero API cost. That
is the point: it shrinks what the once-daily Sonnet brief has to write about (and
stops one event producing many alerts), without paying to dedupe.

`collapse_stories` is safe to run more than once on the same items: an item that
already carries `corroboration` has its counts MERGED rather than reset, so the
per-run pass (before routing) and the whole-buffer pass (before the brief, which
catches duplicates that arrived in different alert runs) compose correctly.
"""

from __future__ import annotations

import difflib
import re

import config

# Title tokens with no discriminating power for "is this the same event?". Tickers,
# entity names, and numbers are deliberately NOT here — they're the strongest signal.
_STOP = {
    "the", "a", "an", "and", "or", "but", "for", "to", "of", "in", "on", "at",
    "as", "by", "is", "are", "be", "was", "were", "with", "from", "into", "over",
    "after", "amid", "says", "say", "said", "new", "news", "report", "reports",
    "update", "amp", "its", "it", "this", "that", "will", "has", "have", "could",
    "may", "than", "more", "out", "up", "down", "off",
}


def _norm(title: str) -> str:
    """Lowercase, drop a trailing 'Headline - Publisher' attribution (Google News
    appends one, and it differs per outlet for the SAME story, which would wrongly
    depress similarity), and squeeze to alphanumeric tokens."""
    t = title.lower()
    if " - " in t:
        head, _, tail = t.rpartition(" - ")
        if head and len(tail.split()) <= 4:  # short tail == publisher, not content
            t = head
    t = re.sub(r"[^a-z0-9%$.]+", " ", t)
    return " ".join(t.split())


def _tokens(title: str) -> set[str]:
    return {w for w in _norm(title).split() if len(w) > 2 and w not in _STOP}


def _similar(a_title: str, b_title: str, a_tokens: set[str], b_tokens: set[str]) -> float:
    """Max of token-set Jaccard (robust to word reordering) and character-sequence
    ratio (robust to near-verbatim wire copy). Both miss reworded-but-same-event
    headlines, which is the intended bias: a missed merge just shows a duplicate,
    while a false merge would hide a distinct story."""
    if a_tokens and b_tokens:
        jaccard = len(a_tokens & b_tokens) / len(a_tokens | b_tokens)
    else:
        jaccard = 0.0
    ratio = difflib.SequenceMatcher(None, _norm(a_title), _norm(b_title)).ratio()
    return max(jaccard, ratio)


def _rep_rank(item: dict) -> tuple:
    """Sort key for choosing a cluster's representative (best-first when sorted
    descending). Triage impact leads when it's present (the post-triage buffer pass,
    preserving the original highest-impact-wins behavior); when it isn't — the
    pre-triage pass, which runs before any item is scored — it falls back to outlet
    count then title length, so the choice is deterministic and needs no triage data."""
    impact = item.get("triage", {}).get("impact", 0)
    corroboration = item.get("corroboration", {}).get("count", 1)
    return (impact, corroboration, len(item.get("title", "")))


def _corroboration(item: dict) -> dict:
    """This item's corroboration record, defaulting to a singleton for a raw item."""
    existing = item.get("corroboration")
    if existing:
        return {
            "count": existing["count"],
            "sources": list(existing["sources"]),
            "titles": list(existing["titles"]),
        }
    return {"count": 1, "sources": [item["source"]] if item.get("source") else [], "titles": []}


def _absorb(into: dict, item: dict) -> None:
    """Fold `item` (and any corroboration it already carried) into a representative's
    corroboration record."""
    other = _corroboration(item)
    into["count"] += other["count"]
    for source in other["sources"]:
        if source not in into["sources"]:
            into["sources"].append(source)
    into["titles"].append(item["title"])
    into["titles"].extend(other["titles"])


def filter_already_alerted(items: list[dict], alerted_titles: list[str], threshold: float | None = None) -> list[dict]:
    """Drop items whose title is similar to any story already alerted today.
    Used in run.py to prevent the same event from generating multiple alert
    emails across successive 30-min runs."""
    if not alerted_titles:
        return items
    if threshold is None:
        threshold = config.STORY_DEDUPE_SIMILARITY
    known_tokens = [_tokens(t) for t in alerted_titles]
    result = []
    for item in items:
        tok = _tokens(item["title"])
        if not any(
            _similar(item["title"], known, tok, ktok) >= threshold
            for known, ktok in zip(alerted_titles, known_tokens)
        ):
            result.append(item)
    return result


def collapse_stories(items: list[dict], threshold: float | None = None) -> list[dict]:
    """Cluster near-identical items by title; return one representative per cluster,
    each carrying a merged `corroboration` record. Runs either BEFORE triage (so one
    event costs one triage call, not one per outlet) or AFTER it (the whole-buffer
    pass before the brief) — `_rep_rank` picks the representative with or without
    triage scores. Output is impact-descending when triaged, matching triage_items'
    contract; pre-triage the order is irrelevant (triage_items re-sorts)."""
    if threshold is None:
        threshold = config.STORY_DEDUPE_SIMILARITY

    # Process best-first so the representative of each cluster is its strongest item.
    order = sorted(items, key=_rep_rank, reverse=True)

    clusters: list[dict] = []  # {"item", "tokens", "corro"}
    for item in order:
        tokens = _tokens(item["title"])
        for cluster in clusters:
            if _similar(item["title"], cluster["item"]["title"], tokens, cluster["tokens"]) >= threshold:
                _absorb(cluster["corro"], item)
                break
        else:
            clusters.append({"item": item, "tokens": tokens, "corro": _corroboration(item)})

    collapsed = [{**c["item"], "corroboration": c["corro"]} for c in clusters]
    collapsed.sort(key=lambda i: i.get("triage", {}).get("impact", 0), reverse=True)
    return collapsed
