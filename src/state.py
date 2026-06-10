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
