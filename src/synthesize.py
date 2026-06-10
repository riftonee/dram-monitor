"""Synthesize: the once-daily morning briefing, written by Claude Sonnet.

Runs once per day over the already-triaged, already-filtered set (so it's cheap
despite the stronger model). Produces a short HTML briefing — what moved the
memory cycle in the last 24h and what it plausibly means for DRAM — leading with
the highest-impact items, grouped by category.

Per BRIEF.md this is awareness, not a trade signal: the prompt is steered to
explain and contextualize, never to advise buying or selling.

Needs ANTHROPIC_API_KEY in the environment.
"""

from __future__ import annotations

import json

import anthropic

MODEL = "claude-sonnet-4-6"

SYSTEM_PROMPT = """\
You write a concise morning briefing for someone tracking the Roundhill Memory \
ETF (DRAM) — a fund of memory-semiconductor companies (Micron, SK hynix, \
Samsung, SanDisk, Seagate, Western Digital) plus the broader memory cycle (HBM, \
DRAM/NAND pricing, AI-driven demand).

You are given the day's already-filtered, impact-scored news items. Write a tight \
briefing that helps the reader understand what happened and why it matters for \
memory — not whether to trade. This is an awareness tool: explain and \
contextualize; never give buy/sell advice or price targets.

Output an HTML fragment (no <html>/<body> wrapper, inline tags only):
1. Open with one or two sentences: the single most important takeaway about the \
state of the memory cycle in the last 24h.
2. Then group the rest under <h3> headings by theme (Fund, Holdings, Pricing, \
Industry), highest-impact first within each. Synthesize — connect related items \
rather than restating each headline. Link the most important source per point \
with <a href>.
3. If items are sparse or minor, say so plainly and keep it short. If there is \
genuinely nothing material, say "Nothing material in the memory cycle today."

Be factual and brief. No preamble like "Here is your briefing"."""

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


def _format_items(items: list[dict]) -> str:
    """Compact JSON lines of the triaged items for the model to synthesize."""
    rows = [
        {
            "impact": i["triage"]["impact"],
            "category": i["triage"]["category"],
            "title": i["title"],
            "source": i["source"],
            "url": i["url"],
            "summary": i["triage"]["summary"],
        }
        for i in items
    ]
    return json.dumps(rows, ensure_ascii=False, indent=1)


def synthesize(items: list[dict]) -> str:
    """Return an HTML briefing fragment for the day's kept items."""
    if not items:
        return "<p>Nothing material in the memory cycle today.</p>"

    response = _get_client().messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        output_config={"effort": "medium"},  # short writing task; medium balances cost/quality
        messages=[
            {
                "role": "user",
                "content": f"Today's filtered memory news ({len(items)} items):\n{_format_items(items)}",
            }
        ],
    )
    return next(b.text for b in response.content if b.type == "text")
