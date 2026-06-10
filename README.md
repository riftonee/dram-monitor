# DRAM monitor

A personal, serverless monitor for the **Roundhill Memory ETF (DRAM)**. It runs on
GitHub Actions, collects memory-industry news, filters noise with an AI triage pass,
and emails a daily briefing plus rare instant alerts. Awareness tool, not a trade
signal — see [`BRIEF.md`](BRIEF.md) for the full design.

## How it works

```
collect → drop stale (>48h) → dedupe (seen.json) → Haiku triage → route → email
```

- **Sources:** Google News RSS (the workhorse, also covers the Korean holdings),
  SEC EDGAR 8-Ks, Finnhub, and Alpha Vantage (daily only — tight free tier).
- **Triage:** `claude-haiku-4-5` scores each item `{relevant, impact 1-5, category}`
  and drops noise before any further spend.
- **Routing:** `impact ≥ 4` → instant alert email; everything kept is accumulated in
  `state/kept_today.json`.
- **Daily brief:** `claude-sonnet-4-6` synthesizes the day's kept items into a
  morning briefing.

## Schedule (GitHub Actions, `.github/workflows/monitor.yml`)

- **Alerts** — every 30 min, 24/7 (memory news breaks during Asia overnight).
- **Brief** — 12:05 UTC (~8am ET), summarizing the whole day; always sent, even on
  quiet days.

## Required GitHub Secrets

Set these in **Settings → Secrets and variables → Actions**:

| Secret | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Haiku triage + Sonnet synthesis |
| `RESEND_API_KEY` | Email delivery |
| `EMAIL_TO` | Recipient |
| `EMAIL_FROM` | Sender (verify a domain in Resend for production) |
| `EDGAR_USER_AGENT` | e.g. `dram-monitor you@example.com` — SEC 403s without a contact |
| `FINNHUB_KEY` | *(optional)* extra ticker news |
| `ALPHA_VANTAGE_KEY` | *(optional)* extra ticker news (daily only) |

## Local development

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env            # fill in keys; .env is gitignored
.venv/bin/python -m src.collect            # print collected items
.venv/bin/python -m src.run brief --dry    # full pipeline, print instead of send
```

Tunables (watchlist queries, tickers, thresholds) live in [`config.py`](config.py).
