"""Run: the per-invocation orchestrator the cron schedule calls.

Pipeline (BRIEF.md). Dedupe happens BEFORE any paid AI step so a story is never
processed twice:

    collect  ->  drop stale (recency)  ->  drop already-seen (dedupe)  ->  [triage/synth/send]

Milestones 1-2 implemented here: collect, recency filter, dedupe, persist state.
Triage/synthesize/notify hook in at steps 4-5.

Run:  python3 -m src.run
"""

from __future__ import annotations

import sys
import time

try:  # Load a local .env for dev; in CI the vars come from GitHub Secrets.
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import config
from src import notify, state
from src.collect import collect_all


def filter_recent(items: list[dict], max_age_hours: int, now: float) -> list[dict]:
    """Keep items newer than the cutoff. Undated items are kept (better to let the
    later AI triage judge them than to silently drop a possibly-fresh story)."""
    cutoff = now - max_age_hours * 3600
    return [i for i in items if i["published_ts"] is None or i["published_ts"] >= cutoff]


def gather_new_items(now: float | None = None) -> list[dict]:
    """Collect, drop stale, drop already-seen, and persist the updated seen-state.
    Returns the fresh items for the downstream (triage -> synth -> send) stages."""
    now = time.time() if now is None else now

    collected = collect_all()
    recent = filter_recent(collected, config.MAX_ITEM_AGE_HOURS, now)

    seen = state.load_seen()
    new = state.filter_new(recent, seen)

    state.mark_seen(seen, new, now)
    state.save_seen(state.prune(seen, now))

    return new, len(collected), len(recent)


def main() -> None:
    send = "--send" in sys.argv[1:]

    new, n_collected, n_recent = gather_new_items()
    for item in new:
        print(f"[{item['topic']:>8}] {item['title']}")
        print(f"           {item['source']} — {item['published_at']}")
        print(f"           {item['url']}")
        print()
    print(
        f"--- collected {n_collected} -> {n_recent} recent "
        f"(<= {config.MAX_ITEM_AGE_HOURS}h) -> {len(new)} new after dedupe ---"
    )

    if send:
        subject = f"DRAM monitor — {len(new)} new item(s)"
        result = notify.send_email(subject, notify.render_raw_list_html(new))
        print(f"--- email sent via Resend (id: {result.get('id', '?')}) ---")


if __name__ == "__main__":
    main()
