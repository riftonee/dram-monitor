"""Run: the per-invocation orchestrator the cron schedule calls.

Pipeline (BRIEF.md). Dedupe happens BEFORE any paid AI step so a story is never
processed twice:

    collect -> drop stale (recency) -> drop seen (dedupe) -> triage -> route -> send

Two modes:
  alerts  (every 30 min) — collect, triage, send instant alerts (impact>=4), and
                           accumulate kept items into the daily buffer.
  brief   (once a day)   — same, plus pull the rate-limited source (Alpha Vantage),
                           synthesize the whole day's buffer into the morning
                           briefing, send it, and clear the buffer.

Instant alerts fire in BOTH modes — they're keyed to this run's newly-seen items,
so each alert-worthy story is emailed exactly once regardless of mode.

Run:  python3 -m src.run alerts        (default)
      python3 -m src.run brief
      python3 -m src.run brief --dry    (print, don't send — for local testing)
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
from src import dedupe, notify, state, synthesize, triage
from src.collect import collect_all


def filter_recent(items: list[dict], max_age_hours: int, now: float) -> list[dict]:
    """Keep items newer than the cutoff. Undated items are kept (better to let the
    later AI triage judge them than to silently drop a possibly-fresh story)."""
    cutoff = now - max_age_hours * 3600
    return [i for i in items if i["published_ts"] is None or i["published_ts"] >= cutoff]


def gather_new_items(include_rate_limited: bool = False, now: float | None = None):
    """Collect, drop stale, drop already-seen, and persist the updated seen-state.
    Returns (new_items, n_collected, n_recent) for the downstream stages."""
    now = time.time() if now is None else now

    collected = collect_all(include_rate_limited=include_rate_limited)
    recent = filter_recent(collected, config.MAX_ITEM_AGE_HOURS, now)

    seen = state.load_seen()
    new = state.filter_new(recent, seen)

    state.mark_seen(seen, new, now)
    state.save_seen(state.prune(seen, now))

    return new, len(collected), len(recent)


def run(mode: str, dry: bool) -> None:
    new, n_collected, n_recent = gather_new_items(include_rate_limited=(mode == "brief"))
    # Collapse near-identical items about the same event (one Micron earnings report
    # -> many outlets) BEFORE triage, so one event costs one triage call instead of
    # one per outlet. Deterministic — no AI cost. (See dedupe.py / CLAUDE.md.)
    stories = dedupe.collapse_stories(new)
    kept = triage.triage_items(stories)  # relevant only, sorted by impact desc
    instant = [i for i in kept if i["triage"]["impact"] >= config.INSTANT_ALERT_IMPACT]
    buffer = state.append_buffer(kept)

    for item in kept:
        v = item["triage"]
        outlets = item.get("corroboration", {}).get("count", 1)
        tag = f" (+{outlets - 1} more)" if outlets > 1 else ""
        print(f"[{v['impact']}/5 {v['category']:>8}] {item['title']}{tag}")
        print(f"           {v['summary']}")
    print(
        f"--- [{mode}] collected {n_collected} -> {n_recent} recent -> {len(new)} new "
        f"-> {len(stories)} stories (triaged) -> {len(kept)} relevant "
        f"({len(instant)} alert); buffer={len(buffer)} ---"
    )

    # Instant alerts: filter out stories already alerted today (cross-run dedup),
    # then send one batched email per run (not one-per-item — that both spams the
    # inbox and trips Resend's 5-requests/sec limit on a backlog).
    alerted_titles = state.load_alerted()
    new_instant = dedupe.filter_already_alerted(instant, alerted_titles)
    suppressed = len(instant) - len(new_instant)
    if suppressed:
        print(f"    [{mode}] suppressed {suppressed} already-alerted story(ies)")
    if new_instant:
        if len(new_instant) == 1:
            v = new_instant[0]["triage"]
            subject = f"🚨 DRAM alert [{v['impact']}/5]: {new_instant[0]['title']}"
        else:
            top = new_instant[0]["triage"]["impact"]
            subject = f"🚨 DRAM: {len(new_instant)} high-impact items (top {top}/5)"
        if dry:
            print(f"    [dry] would send 1 alert email covering {len(new_instant)} item(s)")
        else:
            notify.send_email(subject, notify.render_digest_html(new_instant))
            state.append_alerted(new_instant)

    if mode == "brief":
        # Synthesize the whole day's buffer, send, then flush. Always sends —
        # even on a quiet day — so a silent failure is distinguishable. Re-collapse
        # across the full buffer first: near-duplicates that arrived in different
        # alert runs (different ids, so the per-run pass never saw them together)
        # only meet here. corroboration counts merge across runs (dedupe.py).
        brief_items = dedupe.collapse_stories(buffer)
        subject = f"DRAM brief — {len(brief_items)} story(ies) today, {len(instant)} alert(s) this run"
        body = synthesize.synthesize(brief_items)
        if dry:
            print(f"    [dry] would send brief ({len(brief_items)} stories)\n{body[:500]}")
        else:
            result = notify.send_email(subject, body)
            state.clear_buffer()
            state.clear_alerted()
            print(f"--- brief sent via Resend (id: {result.get('id', '?')}); buffer + alerted cleared ---")


def main() -> None:
    args = sys.argv[1:]
    mode = "brief" if "brief" in args else "alerts"
    dry = "--dry" in args
    run(mode, dry)


if __name__ == "__main__":
    main()
