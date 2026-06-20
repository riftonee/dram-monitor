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

`collect → drop stale (recency) → drop already-seen (exact-URL dedupe) → collapse same-story (semantic dedupe) → Haiku triage → route → send`

Both dedupe layers **must** stay before the AI call so a story is never paid to triage twice: exact-URL (`seen.json`) drops repeats across runs, and same-story collapse (`dedupe.py`) drops near-identical outlet copies within a run. Modules (`src/`):

- `collect.py` — all source fetchers, normalized to `{id, source, topic, title, url, published_at, published_ts, snippet}`. `collect_all(include_rate_limited=False)`; Alpha Vantage is gated behind that flag (its free tier is ~25 req/day). Every fetcher is defensive — a failing source logs and contributes nothing.
- `state.py` — two JSON stores in `state/`, both committed back each run: `seen.json` (dedupe memory, pruned at 30d) and `kept_today.json` (the daily buffer — see below).
- `triage.py` — per-item relevance + impact scoring, forced JSON, drops `relevant:false`. The schema is a pydantic model (`TriageVerdict`) — the single source of truth both backends use.
- `synthesize.py` — once-daily HTML briefing over the buffer.
- `llm.py` — provider-agnostic shim for the two AI calls. `generate_json(task, …)` / `generate_text(task, …)` dispatch to **Anthropic** (Haiku triage / Sonnet brief) or **Gemini Flash** based on `config.LLM_PROVIDER`. SDK imports are lazy, so a deployment using only one provider needn't install the other's package. The Gemini path forces JSON via `response_schema` (the same pydantic model), disables thinking (`thinking_budget=0`) so it can't eat the output budget, and retries on 429 (free-tier rate limit) with exponential backoff.
- `notify.py` — Resend email via stdlib HTTP.
- `run.py` — the orchestrator; `config.py` (root) holds the watchlist, queries, thresholds, and the LLM provider/model selection.

### LLM provider switch

`config.LLM_PROVIDER` (env `LLM_PROVIDER`, default `anthropic`) chooses the backend for **both** AI calls; `GEMINI_API_KEY` is needed when it's `gemini`. Per-task model ids are independently overridable via `ANTHROPIC_TRIAGE_MODEL` / `ANTHROPIC_BRIEF_MODEL` / `GEMINI_TRIAGE_MODEL` / `GEMINI_BRIEF_MODEL`. Motivation: the every-30-min triage pass is the cost driver, and Gemini Flash's free tier is far cheaper there. The switch is all-or-nothing across tasks today (one provider for the whole run); to split (e.g. Gemini triage + Anthropic brief) you'd extend `llm._MODELS` to allow a per-task provider.

### The two-mode split (key design point)

`run.py` has two modes because alerts and the brief run on different cadences:

- **`alerts`** (every 30 min) — collect, triage, send instant alerts (impact ≥ 4), append kept items to the daily buffer.
- **`brief`** (once a day, 12:05 UTC) — same, plus Alpha Vantage, then synthesize the **whole day's buffer** and clear it.

Why the buffer exists: dedupe marks each item seen on first encounter, so by 8am the brief would see "0 new" — every item was already consumed by an alert run. `kept_today.json` accumulates the day's kept items so the brief can summarize all of them. Instant alerts fire in *both* modes (keyed to this run's newly-seen items), so each alert-worthy story emails exactly once.

**Brief is triggered externally, not by GitHub cron (changed 2026-06-11).** GitHub's scheduled cron is best-effort and was slipping the 12:05 UTC brief by ~4h (landing ~9am PT instead of ~5am PT). So `monitor.yml` only schedules the `*/30` alerts cron; the brief is fired punctually by an **external scheduler (cron-job.org)** that POSTs to the GitHub `workflow_dispatch` API (`.../actions/workflows/monitor.yml/dispatches`, body `{"ref":"main","inputs":{"mode":"brief"}}`) at 12:05 UTC, authed with a fine-grained PAT (Actions: read/write) in an `Authorization: Bearer` header. The "Determine mode" step resolves scheduled runs to `alerts`, so only a `workflow_dispatch` with `mode=brief` produces a brief. 12:05 UTC is chosen to sit *after* the Asian trading day closes (Korea/Taiwan — the leading memory indicators) while still landing in early Pacific morning. A concurrency group serializes runs so state pushes can't race. **Watch-out: if the PAT expires the brief silently stops** (a cloud reminder routine is set for 2027-06-07, a few days before the current token's 2027-06-11 expiry).

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
- **Model strings** `claude-haiku-4-5` / `claude-sonnet-4-6` are current as written. Haiku rejects the `effort` param; don't add it there. (Anthropic-only `effort` is set in `synthesize.py` and ignored by the Gemini path in `llm.py`.)
- **Gemini 2.5 Flash thinks by default**, and thinking tokens count against `max_output_tokens` — left on, a busy brief or a tight triage budget can truncate. `llm.py` sets `thinking_budget=0` for both calls. Gemini structured output uses `response_schema` + `response_mime_type="application/json"`, not Anthropic's `output_config.format`.

## Same-story dedup (built 2026-06-14)

`src/dedupe.py` collapses near-identical items about one event (a single Micron earnings report → many near-identical headlines) so one event yields one alert and one brief entry. It's a **semantic** layer, separate from `seen.json`'s exact-URL dedup (which deliberately stays exact-only). `dedupe.collapse_stories()` clusters by normalized-title similarity (token-set Jaccard ∨ char-sequence ratio, threshold `config.STORY_DEDUPE_SIMILARITY`, default 0.7), keeps one member as the representative (`_rep_rank`: **highest triage impact** when items are already scored, else **most outlets then longest title** — so it works before triage has run), and attaches a `corroboration` record (`count`, `sources`, `titles`). Deterministic — **no AI call**, so it adds zero API cost. The point is twofold: collapsing **before** triage means one event costs **one Haiku call instead of one per outlet** (the main cost lever), and it also shrinks what the paid Sonnet brief writes about.

- Runs in `run.py` **before `triage.triage_items()`** on each run's new items (so syndicated copies of one event collapse before any is triaged — one triage call per event, then one alert and one buffer entry) and **again over the whole buffer before the brief** (catches near-dupes that arrived in separate alert runs — different ids, so the per-run pass never saw them together; buffer items are already scored, so that pass uses the impact-based representative). `collapse_stories` is safe to re-run: an item that already carries `corroboration` has its counts **merged**, not reset.
- **Trade-off of collapsing before triage** (changed 2026-06-20): only the representative is triaged, so its relevance/impact verdict stands for the whole cluster — and the pre-triage pass clusters *all* new items, so an irrelevant sibling can now join a cluster. At threshold 0.7 this only clusters near-verbatim copy that scores the same, so the mis-routing risk is low; raise `STORY_DEDUPE_SIMILARITY` toward 0.8 to be more conservative. (Previously every item was triaged first and collapse kept the max-impact member, max-pooling impact across outlets; now one verdict speaks for the event.)
- Deliberately **conservative**: it catches near-verbatim/syndicated copy, not reworded-same-event headlines. A missed merge only shows a duplicate; a false merge would hide a distinct story. Raise the threshold toward 1.0 to merge less.
- Corroboration surfaces in both outputs: the alert digest shows "(+N more outlet(s))" (`notify.render_digest_html`) and the brief input includes `corroborating_outlets` so Sonnet can flag widely-covered events (`synthesize._format_items` + a prompt note).

## Planned enhancements (not yet built)

- **Holdings auto-refresh.** The watchlist should self-update from the fund's daily holdings file on rebalance (BRIEF.md milestone 7); currently `config.py` lists holdings statically.

## Secrets (GitHub Secrets / local `.env`)

`ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `EMAIL_TO`, `EMAIL_FROM`, `EDGAR_USER_AGENT`, and optionally `LLM_PROVIDER` + `GEMINI_API_KEY`, `FINNHUB_KEY`, `ALPHA_VANTAGE_KEY`. Never commit `.env`. The repo is public (unlimited Actions minutes); all secrets live in GitHub Secrets.

- **LLM backend** — `LLM_PROVIDER` (default `anthropic`). Set it to `gemini` and add `GEMINI_API_KEY` (free tier: https://aistudio.google.com/apikey) to run triage + brief on Gemini Flash. When `anthropic`, `GEMINI_API_KEY` is unused (and vice versa). For GitHub Actions, add the chosen provider's key as a repo Secret and surface it as an env var in `monitor.yml`.
- **`EMAIL_TO` supports multiple recipients** — a comma-separated list (e.g. `a@x.com, b@y.com`); `notify.py` splits/trims it into Resend's `to` array. A single address still works (one-item list).
- **`EMAIL_FROM` should be an address on a Resend-verified domain** for production (e.g. `dram-monitor@yourdomain.com`; the local part is arbitrary and needs no mailbox). The shared `onboarding@resend.dev` test sender only delivers to your own Resend-account email, so it can't reach additional recipients.
