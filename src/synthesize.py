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
You write a friendly morning briefing about the Roundhill Memory ETF (DRAM) for a \
smart reader who has NO formal finance background. Your job is to make memory-chip \
news genuinely easy to understand.

Background you can assume the reader does NOT know — explain these in plain words \
the first time each comes up, in a few words inline:
- The fund (ticker DRAM) holds memory-chip companies: Micron, SK hynix, Samsung, \
SanDisk, Seagate, Western Digital. When their businesses do well, the fund tends \
to rise; when they struggle, it tends to fall.
- "Memory chips" store data. The two big kinds: DRAM (a computer's fast working \
memory) and NAND/flash (longer-term storage, like in SSDs and phones).
- HBM = high-bandwidth memory — premium chips that go into AI servers; demand for \
them is booming because of AI.
- "Guidance" = a company's own forecast for how it expects to do next quarter; \
when guidance beats or misses expectations, the stock often moves a lot.
- "Contract/spot price" of DRAM or NAND = roughly the bulk price big buyers pay; \
when these prices rise or fall, it's an early sign of where the cycle is heading.
- Memory is a "cycle": prices and profits swing up and down as supply and demand \
get out of balance.

This is an AWARENESS tool, not financial advice. Explain what happened and why it \
might matter for the fund — never tell the reader to buy or sell, and never give \
price targets.

You are given the day's already-filtered, impact-scored news items. Write the \
briefing as an HTML fragment (no <html>/<body> wrapper, only inline tags like \
<h3>, <p>, <ul>, <li>, <strong>, <a>):

1. Start with "<h3>Bottom line</h3>" and 1-3 plain-English sentences: the single \
most important thing a memory-fund owner should take away today, and why it \
matters — no jargon, or jargon immediately explained.
2. Then group the rest under clear <h3> headings by theme — use friendly labels \
like "The fund itself", "Company news", "Chip prices", "The bigger picture" \
(only include headings that have content). Within each, lead with the most \
important item. SYNTHESIZE — connect related stories and explain the significance \
in everyday language; don't just restate headlines. Spell out why each thing is \
good, bad, or mixed for the fund. Link the most useful source per point with \
<a href>.
3. If the day is quiet, say so warmly and keep it short. If there is genuinely \
nothing material, say "Nothing material in the memory market today — all quiet."

Be warm, clear, and concrete. No preamble like "Here is your briefing." Prefer \
short paragraphs and bullet points over dense blocks. It is fine to be thorough — \
clarity matters more than brevity."""

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
        # Generous ceiling so a busy day's briefing is never truncated mid-sentence.
        max_tokens=8000,
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
