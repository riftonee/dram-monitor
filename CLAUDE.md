# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status: design-only, not yet implemented

The repo currently contains a single design document, `BRIEF.md`. No code, `requirements.txt`, workflow, or `state/` directory exists yet. `BRIEF.md` is the source of truth for intent — read it before writing code. The structure below is the *planned* target, not the current state.

## What this is

A personal, cron-scheduled monitor for the **Roundhill Memory ETF (DRAM)**. It collects memory-industry news, filters noise with an AI triage pass, and emails the owner a daily briefing plus rare instant alerts. It is an *awareness* tool, explicitly **not** a trading signal (see Non-Goals in `BRIEF.md`). It reuses the "Oceania monitor" / "cruise monitor" pattern: serverless, runs entirely inside GitHub Actions, state committed back to the repo as JSON.

## Architecture (the big picture)

The whole thing is one Python pipeline invoked per Actions run. The ordering of stages is load-bearing:

1. **Collect** → normalize every source item to `{id, source, ticker/topic, title, url, published_at, snippet}`.
2. **Dedupe** against `state/seen.json` — **must happen before any AI call** so the same story is never paid for twice. `id` is the URL or a hash of title+source.
3. **Triage (Haiku, per item)** → forced JSON `{relevant, impact 1-5, category, summary}`. Drop `relevant:false`.
4. **Route** → `impact >= 4` triggers an instant-alert email (and is also kept for the brief); everything else is held.
5. **Synthesize (Sonnet, once/day)** → short briefing over the day's kept items, grouped by category, highest-impact first.
6. **Send (Resend)** → then update `state/seen.json` and commit it back.

Planned layout: `src/{collect,triage,synthesize,notify,state}.py`, `config.py` (watchlist/queries/thresholds), `state/seen.json`, `.github/workflows/monitor.yml`, `requirements.txt`.

## Critical domain rules (easy to get wrong)

- **Never naive-search the word "DRAM".** It floods with memory-technology trivia. Always scope by ticker (MU, SNDK, STX, WDC) or by the curated topic queries in `BRIEF.md` (e.g. `HBM demand`, `DRAM contract price`, `SK Hynix`).
- **DRAM is an ETF — there is no single ticker.** Monitor the holdings, the industry theme, and the fund itself. The watchlist should self-update from the fund's daily holdings file on rebalance.
- **The two Korean holdings (SK Hynix KRX:000660, Samsung KRX:005930) don't appear cleanly in US ticker news APIs.** Cover them via Google News RSS / Reuters / Yonhap queries, and lean on Haiku/Sonnet to translate Korean coverage inline.
- **Memory pricing is the leading indicator** — DRAM/NAND spot/contract pricing (TrendForce/DRAMeXchange via Google News RSS) often moves before earnings.
- **Keep alerts rare.** `impact >= 4` only. A noisy inbox defeats the purpose. The daily brief always sends — even on quiet days ("nothing material") — so a silent failure is distinguishable from a quiet day.

## AI / model notes

- Two models on purpose: **`claude-haiku-4-5`** for cheap per-headline triage, **`claude-sonnet-4-6`** for the once-daily synthesis. Confirm the latest model strings against the Claude API docs at build time.
- Force Haiku to return **JSON only** (no prose, no markdown fences) and parse defensively.
- Use **prompt caching** for the system prompt + watchlist context so repeated 30-min runs don't re-pay for it.

## Build order

Follow the milestones in `BRIEF.md`: Google News RSS collect → dedupe/`seen.json` → Resend daily send → Haiku triage+route → Sonnet synthesis → add Alpha Vantage/Finnhub/EDGAR → instant alerts + holdings auto-refresh. Start cheapest-path-to-working.

## Operational constraints

- **Schedule:** every 30 min, active ~6:00am–midnight ET (wide on purpose — SK Hynix/Samsung earnings and TrendForce pricing break during Asia overnight). Daily brief at ~7:00–8:00am ET.
- **Secrets live in GitHub Secrets**, never in code: `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `ALPHA_VANTAGE_KEY`, `FINNHUB_KEY`, `EMAIL_TO`, `EMAIL_FROM`.
- Every-30-min runs brush the ~2,000 free Actions-minutes/month cap on a *private* repo. Keeping the repo **public** (all secrets are in GitHub Secrets) buys unlimited minutes — this is an open decision in `BRIEF.md`.
