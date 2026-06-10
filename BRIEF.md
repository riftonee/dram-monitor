# BRIEF.md — DRAM Memory Monitor

## Purpose
A personal, scheduled monitoring tool that tracks news and signals relevant to the **Roundhill Memory ETF (DRAM)**, filters out noise with an AI triage pass, and emails me (1) one daily briefing every morning and (2) rare instant alerts when something genuinely material breaks. This is an *awareness* tool, not a trading signal — see Non-Goals.

## Stack (reuse the Oceania monitor pattern)
- **Runtime:** GitHub Actions, cron-scheduled. No server.
- **Language:** Python 3.11+.
- **AI:** Anthropic API — `claude-haiku-4-5` for per-item triage, `claude-sonnet-4-6` for the daily synthesis. (Confirm latest model strings against the API docs at build time.)
- **Email:** Resend.
- **State:** a JSON file (`state/seen.json`) committed back to the repo for dedupe, exactly like the cruise monitor.

---

## The Watchlist (this is the heart of it)
DRAM is an ETF, so there is no single ticker to follow — track the holdings, the industry, and the fund itself.

**Holdings to monitor (verify/refresh from the fund's daily holdings file):**
- SK hynix (Korea, KRX:000660) — largest position
- Samsung Electronics (Korea, KRX:005930)
- Micron Technology (NASDAQ: MU) — large weight, held via swaps
- SanDisk (NASDAQ: SNDK)
- Seagate (NASDAQ: STX)
- Western Digital (NASDAQ: WDC)

**Industry / theme topics (the leading indicators):**
- DRAM and NAND spot/contract pricing (memory is a commodity cycle — pricing often moves the stocks before earnings do)
- HBM (high-bandwidth memory) demand and capacity
- AI infrastructure capex (Nvidia, hyperscalers) as it pulls memory demand
- Memory supply/production cuts, fab capacity, capex changes

**Fund-level:**
- The DRAM ETF itself (flows, rebalances, NAV, fund news)
- Pull the daily holdings file so the watchlist self-updates on rebalance

---

## Data Sources (tiered)
Start with the free tier; add others only if coverage feels thin.

1. **Holdings news APIs (core signal)**
   - **Alpha Vantage `NEWS_SENTIMENT`** — free, query by ticker AND topic, returns sentiment scores. Good primary source. Tickers: MU, SNDK, STX, WDC.
   - **Finnhub** — free company-news-by-ticker as a second source.
   - Marketaux / GNews / NewsAPI — optional general backups.

2. **Google News RSS (free workhorse, no API key)**
   - Build one feed per query. Suggested queries: `Micron guidance`, `SK Hynix`, `Samsung memory`, `HBM demand`, `DRAM prices`, `NAND prices`, `memory chip shortage`.
   - **This is also how the two Korean holdings get covered** — SK Hynix and Samsung won't appear cleanly in US ticker APIs. Supplement with Reuters / Yonhap queries.

3. **Memory pricing (leading indicator)**
   - TrendForce / DRAMeXchange coverage via Google News RSS queries (`TrendForce DRAM`, `DRAM contract price`).

4. **SEC EDGAR (free API)**
   - Filings for the US holdings (MU, SNDK, STX, WDC) — 8-Ks, earnings, guidance.

5. **Fund source**
   - Roundhill DRAM fund page + daily holdings file.

> **Important filtering rule:** never do a naive search for the word "DRAM" — it floods with memory-technology trivia. Always scope by ticker or by the curated topic queries above.

---

## Pipeline (per run)
1. **Collect** — pull all sources, normalize each item to `{id, source, ticker/topic, title, url, published_at, snippet}`. Use URL (or a hash of title+source) as the dedupe id.
2. **Dedupe** — drop anything whose id is already in `state/seen.json`. Only new items proceed. (Dedupe BEFORE the AI step so we never pay to summarize the same story twice.)
3. **Triage (Haiku)** — for each new item, return structured JSON:
   ```json
   {
     "relevant": true,
     "impact": 1-5,
     "category": "holding | industry | pricing | macro | fund",
     "summary": "one line"
   }
   ```
   Drop `relevant: false`. Route the rest by impact.
4. **Route**
   - `impact >= 4` → **instant alert** email (and still include in the next daily brief).
   - everything else → held for the daily brief.
5. **Synthesize (Sonnet, once per day)** — feed the day's kept items to Sonnet for a short briefing: *what moved memory in the last 24h and what it plausibly means for DRAM.* Group by category, lead with the highest-impact items.
6. **Send** — Resend. Update `state/seen.json` and commit it back.

---

## AI Design Notes
- **Two models on purpose:** Haiku is cheap enough to run over every new headline; Sonnet only runs once a day over the already-filtered set.
- **Prompt caching:** cache the system prompt + watchlist context so repeated runs don't re-pay for it.
- **Structured output:** force Haiku to return JSON only (no prose, no markdown fences) and parse defensively.
- **Translation bonus:** Haiku/Sonnet can translate and summarize Korean-language SK Hynix / Samsung coverage inline — lean on this, most retail tools miss it.
- **Batch API:** only needed if backfilling history; not required for steady-state.

---

## Scheduling & Email Cadence
- **Check frequency:** every 30 minutes.
- **Active window:** ~6:00am–midnight ET (wide on purpose — a lot of memory news, including SK Hynix/Samsung earnings and TrendForce pricing, breaks during Asia hours overnight US time).
- **Daily brief:** one email at ~7:00–8:00am ET (captures the full Asia overnight cycle + prior US close in one read). Always send, even on quiet days ("nothing material") so I never wonder if it broke.
- **Instant alerts:** only for `impact >= 4`. Rare by design.
- **Optional weekly roundup:** Sunday "state of the memory cycle." (Build later, flag as TODO.)

> **GitHub Actions cost note:** every-30-min runs will brush the ~2,000 free Action-minutes/month limit on a *private* repo. Either keep the repo **public** (nothing sensitive lives in code — all keys go in GitHub Secrets) for unlimited free minutes, or narrow the active window.

---

## Repo Structure (suggested)
```
dram-monitor/
  .github/workflows/monitor.yml   # cron schedule + run
  src/
    collect.py                    # all source fetchers
    triage.py                     # Haiku per-item JSON
    synthesize.py                 # Sonnet daily brief
    notify.py                     # Resend email
    state.py                      # load/save seen.json
  state/seen.json
  config.py                       # watchlist, queries, thresholds
  requirements.txt
  README.md
```

## Secrets (GitHub Secrets / env)
- `ANTHROPIC_API_KEY`
- `RESEND_API_KEY`
- `ALPHA_VANTAGE_KEY`
- `FINNHUB_KEY`
- `EMAIL_TO`, `EMAIL_FROM`

## Build Order (milestones)
1. Collect from Google News RSS only → print items. (Cheapest path to "is this working.")
2. Add dedupe + `seen.json`.
3. Add Resend; send a raw list daily. Confirm delivery.
4. Add Haiku triage; filter + route by impact.
5. Add Sonnet daily synthesis.
6. Add Alpha Vantage + Finnhub + EDGAR sources.
7. Add instant-alert path and the holdings-file auto-refresh.

---

## Non-Goals / Guardrails
- This does **not** tell me when to buy or sell. By the time news is public, price has often already moved. It exists so I don't *miss* a major development, nothing more.
- For the actual "sell at a target price" job, use my broker's free price alerts — separate from this tool.
- Keep alerts rare. A noisy inbox gets ignored, which defeats the purpose.
- Not financial advice; this is a personal awareness utility.

## Open Decisions (confirm before/while building)
- Confirm current DRAM holdings against the live holdings file (weights shift on rebalance).
- Public vs private repo (drives the Actions-minutes tradeoff above).
- Daily-brief send time and timezone.
- Impact threshold for instant alerts (default: 4 of 5).