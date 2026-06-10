# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A personal, cron-scheduled monitor for the **Roundhill Memory ETF (DRAM)**. It collects memory-industry news, filters noise with an AI triage pass, and emails a daily briefing plus rare instant alerts. It is an *awareness* tool, explicitly **not** a trading signal (see Non-Goals in `BRIEF.md`). Serverless: runs entirely inside GitHub Actions, state committed back to the repo as JSON. `BRIEF.md` is the original design spec; this file and the code are the current truth.

## Commands

```sh
# Setup
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # fill in keys (gitignored)

# Run
.venv/bin/python -m src.collect          # print collected items (add --all for Alpha Vantage)
.venv/bin/python -m src.run alerts        # every-30-min path: triage + instant alerts
.venv/bin/python -m src.run brief         # daily path: + Alpha Vantage + synthesized brief
.venv/bin/python -m src.run brief --dry   # full pipeline but PRINT instead of send/clear
```

There is no test suite yet. Verify changes with `--dry` (no email sent, buffer not cleared) and by re-running to confirm dedupe drives new-item count to 0.

## Architecture (the big picture)

One Python pipeline, invoked per Actions run. The stage ordering is load-bearing:

`collect → drop stale (recency) → drop already-seen (dedupe) → Haiku triage → route → send`

Dedupe **must** stay before any AI call so a story is never paid for twice. Modules (`src/`):

- `collect.py` — all source fetchers, normalized to `{id, source, topic, title, url, published_at, published_ts, snippet}`. `collect_all(include_rate_limited=False)`; Alpha Vantage is gated behind that flag (its free tier is ~25 req/day). Every fetcher is defensive — a failing source logs and contributes nothing.
- `state.py` — two JSON stores in `state/`, both committed back each run: `seen.json` (dedupe memory, pruned at 30d) and `kept_today.json` (the daily buffer — see below).
- `triage.py` — `claude-haiku-4-5`, forced JSON via `output_config.format`, drops `relevant:false`.
- `synthesize.py` — `claude-sonnet-4-6`, once-daily HTML briefing over the buffer.
- `notify.py` — Resend email via stdlib HTTP.
- `run.py` — the orchestrator; `config.py` (root) holds the watchlist, queries, and thresholds.

### The two-mode split (key design point)

`run.py` has two modes because alerts and the brief run on different cadences:

- **`alerts`** (every 30 min) — collect, triage, send instant alerts (impact ≥ 4), append kept items to the daily buffer.
- **`brief`** (once a day, 12:05 UTC) — same, plus Alpha Vantage, then synthesize the **whole day's buffer** and clear it.

Why the buffer exists: dedupe marks each item seen on first encounter, so by 8am the brief would see "0 new" — every item was already consumed by an alert run. `kept_today.json` accumulates the day's kept items so the brief can summarize all of them. Instant alerts fire in *both* modes (keyed to this run's newly-seen items), so each alert-worthy story emails exactly once.

The workflow (`.github/workflows/monitor.yml`) picks the mode from `github.event.schedule`; the brief cron is `5 12 * * *` (a non-`:00`/`:30` minute) so it never collides with the `*/30` alerts cron, and a concurrency group serializes runs so state pushes can't race.

## Critical domain rules (easy to get wrong)

- **Never naive-search the word "DRAM".** It floods with memory-technology trivia. Scope by ticker (MU, SNDK, STX, WDC) or curated topic queries in `config.py`. This rule lives in the Haiku triage system prompt too.
- **DRAM is an ETF — no single ticker.** Monitor holdings + industry + the fund itself.
- **The Korean holdings (SK hynix, Samsung) don't appear in US ticker APIs** (Finnhub/Alpha Vantage). They're covered only via Google News queries; Haiku is told to translate Korean coverage inline.
- **Pricing is the leading indicator** — DRAM/NAND spot/contract prices often move before earnings.
- **Keep alerts rare** (impact ≥ 4 only) and **always send the brief** — even on quiet days — so a silent failure is distinguishable.

## Gotchas baked into the code

- **SEC EDGAR** uses the submissions JSON API (`data.sec.gov`), not the browse-edgar atom feed (its `<content>` embeds raw HTML that breaks XML parsing). It **403s without a contact-email `EDGAR_USER_AGENT`** and then contributes nothing silently.
- **Resend is behind Cloudflare** — the default `Python-urllib` User-Agent gets a 403 (error 1010); `notify.py` sends a real UA.
- **Google News URLs are redirect links** (`news.google.com/rss/articles/...`). Stable for dedupe; not yet resolved to publisher URLs.
- **Model strings** `claude-haiku-4-5` / `claude-sonnet-4-6` are current as written. Haiku rejects the `effort` param; don't add it there.

## Planned enhancements (not yet built)

- **Same-story dedup (confirmed wanted — 2026-06-10).** Many outlets cover one event (e.g. a single Micron earnings report → 7 near-identical headlines), each legitimately scoring 5, so one event produces many alerts. The triage rubric is already tightened to reserve 4-5 for concrete events (so this is no longer a *scoring* issue) and alerts are batched into one email per run (so it's not an *inbox* issue) — but the day's brief and the alert digest still list the same event many times. Plan: collapse near-identical items about the same event *after* triage and *before* routing/synthesis — e.g. cluster by entity + event/number or by normalized-title similarity, keep the highest-impact representative (and optionally a count of corroborating outlets). The `seen.json` dedup is exact-URL only and deliberately stays that way; this is a separate semantic-dedup layer. Likely lives between `triage.triage_items()` and routing in `run.py`, and should also collapse items before they enter the daily buffer.
- **Holdings auto-refresh.** The watchlist should self-update from the fund's daily holdings file on rebalance (BRIEF.md milestone 7); currently `config.py` lists holdings statically.

## Secrets (GitHub Secrets / local `.env`)

`ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `EMAIL_TO`, `EMAIL_FROM`, `EDGAR_USER_AGENT`, and optionally `FINNHUB_KEY`, `ALPHA_VANTAGE_KEY`. Never commit `.env`. The repo is public (unlimited Actions minutes); all secrets live in GitHub Secrets.
