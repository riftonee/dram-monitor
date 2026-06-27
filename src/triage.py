"""Triage: per-item relevance + impact scoring with Claude Haiku.

Each new item is scored with structured JSON output (forced via output_config,
so the response is guaranteed schema-valid — no defensive parsing needed). Items
with relevant=false are dropped before they ever reach the daily synthesis, and
impact drives routing (instant alert vs. held for the brief).

The watchlist context lives in the system prompt so the model knows what "relevant"
means for THIS fund. Per BRIEF.md: the bare word "DRAM" is noise — relevance is
scoped to the holdings, the memory industry, pricing, and the fund itself.

The actual model call goes through src/llm.py, which dispatches to Anthropic
(Haiku) or Gemini Flash based on config.LLM_PROVIDER. Needs the active provider's
API key in the environment (ANTHROPIC_API_KEY or GEMINI_API_KEY).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from src import llm

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

Impact scale (1-5) — reserve 4 and 5 for stories reporting a CONCRETE EVENT or a \
HARD NUMBER, not opinion or possibility:
- 5 = a confirmed, market-moving event that introduces NEW information: the initial \
earnings release itself, an unexpected guidance change materially different from \
prior guidance, an announced supply/production cut or demand shock, or a large \
price move with a distinct catalyst that is NOT downstream of an already-released \
earnings print. Analyst reactions, price-target changes, and stock moves that are \
simply the market digesting a known earnings report are at most a 3 — do not score \
them 5 even if the magnitude is large.
- 4 = a concrete, material development that has actually happened: a signed or \
officially announced deal, a substantive regulatory filing, an official \
capacity/investment decision, or a sizable confirmed stock move whose cause is \
distinct from the same session's earnings release.
- 3 = relevant but soft — opinion, analysis, or possibility rather than a settled \
event. Includes analyst notes and price-target changes; post-earnings stock moves \
and "stock rose/fell X%" pieces driven by already-reported results; deals merely \
being discussed, pursued, explored, or rumored; and executives "meeting to discuss". \
When torn between 3 and 4, pick 3.
- 2 = minor or passing mention. 1 = trivial.

Only impact 4-5 triggers an instant alert, so be strict: if the story is talk, \
speculation, a forecast, or a pure price move with no stated cause, it is at most \
a 3. Category is the dominant theme.

Translate non-English (e.g. Korean SK hynix/Samsung) coverage as needed."""

# Forced structured-output schema — the single source of truth for both backends.
# llm.py renders this to Anthropic's strict JSON schema and passes it straight to
# the Gemini SDK, so the verdict is guaranteed schema-valid either way (no
# defensive parsing needed downstream).
class TriageVerdict(BaseModel):
    relevant: bool
    impact: Literal[1, 2, 3, 4, 5]
    category: Literal["holding", "industry", "pricing", "macro", "fund"]
    summary: str


def triage_item(item: dict) -> dict:
    """Return the parsed triage verdict for one item: {relevant, impact, category, summary}."""
    snippet = item.get("snippet", "")[:500]
    user = (
        f"Headline: {item['title']}\n"
        f"Source: {item['source']}\n"
        f"Matched query topic: {item['topic']}\n"
        f"Snippet: {snippet}"
    )
    return llm.generate_json(
        "triage", SYSTEM_PROMPT, user, schema=TriageVerdict, max_tokens=512
    )


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
