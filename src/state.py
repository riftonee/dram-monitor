"""State: the dedupe memory in state/seen.json, committed back to the repo each run.

Shape on disk:
    {"seen": {"<id>": <first_seen_epoch>, ...}}

`id` is the stable hash produced in collect.py. We store the first-seen timestamp
(not just the id) so the file can be pruned and never grows without bound.
"""

from __future__ import annotations

import json
import os
import time

import config

SEEN_PATH = os.path.join("state", "seen.json")
# The day's kept (relevant, triaged) items, accumulated by the frequent alert
# runs and flushed by the once-daily brief. Without this, the brief would see
# "0 new" — every item was already consumed (and marked seen) by an alert run.
BUFFER_PATH = os.path.join("state", "kept_today.json")


def load_seen() -> dict[str, float]:
    """Return {id: first_seen_epoch}. Empty (not an error) if the file is absent."""
    if not os.path.exists(SEEN_PATH):
        return {}
    with open(SEEN_PATH, encoding="utf-8") as f:
        return json.load(f).get("seen", {})


def save_seen(seen: dict[str, float]) -> None:
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump({"seen": seen}, f, indent=2, sort_keys=True)


def filter_new(items: list[dict], seen: dict[str, float]) -> list[dict]:
    """Keep only items whose id is not already in `seen`, deduping within the batch
    too (the same article often arrives from more than one query)."""
    new: list[dict] = []
    batch_ids: set[str] = set()
    for item in items:
        item_id = item["id"]
        if item_id in seen or item_id in batch_ids:
            continue
        batch_ids.add(item_id)
        new.append(item)
    return new


def mark_seen(seen: dict[str, float], items: list[dict], now: float | None = None) -> dict[str, float]:
    now = time.time() if now is None else now
    for item in items:
        seen.setdefault(item["id"], now)
    return seen


def prune(seen: dict[str, float], now: float | None = None) -> dict[str, float]:
    """Drop ids older than SEEN_RETENTION_DAYS so the file stays small."""
    now = time.time() if now is None else now
    cutoff = now - config.SEEN_RETENTION_DAYS * 86400
    return {k: v for k, v in seen.items() if v >= cutoff}


# --- Daily kept-items buffer (for the morning brief) -----------------------


def load_buffer() -> list[dict]:
    if not os.path.exists(BUFFER_PATH):
        return []
    with open(BUFFER_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_buffer(items: list[dict]) -> None:
    os.makedirs(os.path.dirname(BUFFER_PATH), exist_ok=True)
    with open(BUFFER_PATH, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=1)


def append_buffer(new_items: list[dict], now: float | None = None) -> list[dict]:
    """Add this run's kept items to the buffer (dedup by id), drop anything older
    than the retention window (safety net if a brief run is ever missed), persist,
    and return the updated buffer."""
    now = time.time() if now is None else now
    buffer = load_buffer()
    have = {i["id"] for i in buffer}
    for item in new_items:
        if item["id"] not in have:
            buffer.append({**item, "buffered_ts": now})
            have.add(item["id"])
    cutoff = now - config.BUFFER_RETENTION_HOURS * 3600
    buffer = [i for i in buffer if i.get("buffered_ts", now) >= cutoff]
    save_buffer(buffer)
    return buffer


def clear_buffer() -> None:
    save_buffer([])


# --- Alerted-today store (for cross-run alert dedup) -----------------------
# Tracks titles of stories that have already triggered an instant alert today.
# Cleared alongside the buffer at each brief run.

ALERTED_PATH = os.path.join("state", "alerted_today.json")


def load_alerted() -> list[str]:
    if not os.path.exists(ALERTED_PATH):
        return []
    with open(ALERTED_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_alerted(titles: list[str]) -> None:
    os.makedirs(os.path.dirname(ALERTED_PATH), exist_ok=True)
    with open(ALERTED_PATH, "w", encoding="utf-8") as f:
        json.dump(titles, f, ensure_ascii=False, indent=1)


def append_alerted(items: list[dict]) -> None:
    titles = load_alerted()
    existing = set(titles)
    for item in items:
        t = item.get("title", "")
        if t and t not in existing:
            titles.append(t)
            existing.add(t)
    save_alerted(titles)


def clear_alerted() -> None:
    save_alerted([])
