"""Triage: per-item relevance + impact scoring with Claude Haiku.

Each new item is scored with structured JSON output (forced via output_config,
so the response is guaranteed schema-valid — no defensive parsing needed). Items
with relevant=false are dropped before they ever reach the daily synthesis, and
impact drives routing (instant alert vs. held for the brief).

The watchlist context lives in the system prompt so Haiku knows what "relevant"
means for THIS fund. Per BRIEF.md: the bare word "DRAM" is noise — relevance is
scoped to the holdings, the memory industry, pricing, and the fund itself.

Needs ANTHROPIC_API_KEY in the environment.
"""

from __future__ import annotations

import json

import anthropic

MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = """\
You triage news for a monitor of the Roundhill Memory ETF (ticker DRAM), a fund \
of memory-semiconductor companies. Decide whether each item is materially \
relevant to that fund and score its impact.

What is relevant — anything that moves the memory cycle or the fund's holdings:
- Holdings: Micron (MU), SK hynix, Samsung (memory/semiconductor arm), SanDisk \
(SNDK), Seagate (STX), Western Digital (WDC).
- Industry: HBM (high-bandwidth memory) demand/capacity, AI-infrastructure capex \
as it pulls memory demand, fab capacity, production cuts.
- Pricing: DRAM/NAND spot or contract prices (a leading indicator — it often \
moves the stocks before earnings).
- Fund: the DRAM ETF itself — flows, NAV, rebalances, fund news.

What is NOT relevant — drop these (relevant=false):
- Generic "computer memory" / RAM-buying-guide / how-DRAM-works trivia.
- A holding mentioned only in passing (e.g. a stock-list roundup) with no \
memory-specific news.
- Unrelated macro/markets stories that merely name-drop the fund.

Impact scale (1-5): 5 = major, market-moving (earnings, big guidance change, \
large price move, supply shock); 4 = clearly material; 3 = notable; 2 = minor; \
1 = trivial. Category is the dominant theme.

Translate non-English (e.g. Korean SK hynix/Samsung) coverage as needed."""

# Forced structured output — the response's first text block is guaranteed to be
# JSON matching this schema. (Haiku 4.5 supports structured outputs.)
SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "boolean"},
        "impact": {"type": "integer", "enum": [1, 2, 3, 4, 5]},
        "category": {
            "type": "string",
            "enum": ["holding", "industry", "pricing", "macro", "fund"],
        },
        "summary": {"type": "string"},
    },
    "required": ["relevant", "impact", "category", "summary"],
    "additionalProperties": False,
}

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


def triage_item(item: dict) -> dict:
    """Return the parsed triage verdict for one item: {relevant, impact, category, summary}."""
    snippet = item.get("snippet", "")[:500]
    user = (
        f"Headline: {item['title']}\n"
        f"Source: {item['source']}\n"
        f"Matched query topic: {item['topic']}\n"
        f"Snippet: {snippet}"
    )
    response = _get_client().messages.create(
        model=MODEL,
        max_tokens=512,
        system=[
            # cache_control marks the stable prefix; our prompt is below Haiku's
            # 4096-token cache minimum so this likely won't cache yet — harmless,
            # and it starts paying off if the watchlist context grows.
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ],
        messages=[{"role": "user", "content": user}],
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
    )
    text = next(b.text for b in response.content if b.type == "text")
    return json.loads(text)


def triage_items(items: list[dict]) -> list[dict]:
    """Triage every item, attach the verdict under 'triage', drop irrelevant ones,
    and return the survivors sorted by impact (highest first)."""
    kept: list[dict] = []
    for item in items:
        verdict = triage_item(item)
        if not verdict["relevant"]:
            continue
        kept.append({**item, "triage": verdict})
    kept.sort(key=lambda i: i["triage"]["impact"], reverse=True)
    return kept
