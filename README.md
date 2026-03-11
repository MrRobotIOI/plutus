# plutus sector explorer

`plutus` is an AI-led macro sector discovery app:

- Scan a built-in universe of major and niche sectors
- Ingest world news from multiple providers
- Detect structured macro events
- Group findings by sector, then by event cluster
- Generate trade ideas with blended news, market, and historical scores

This is a research/signal tool, **not** an automated execution bot and **not** financial advice.

## Features

- News ingestion:
  - Uses `NewsAPI` and `Finnhub` when keys are set
  - Falls back to built-in mock headlines for instant demo
- Event detection:
  - Uses OpenAI if `OPENAI_API_KEY` is set
  - Falls back to deterministic heuristics
- Sector-first scan:
  - Broad default scan or optional watchlist narrowing
  - Grouped by sector/theme first, then event clusters
- Scoring:
  - `news_score`, `market_score`, and `historical_score`
  - `final_score = 0.45 * news + 0.35 * market + 0.20 * historical`
  - `Polygon` and `Finnhub` can power live stock/ETF market confirmation
  - `FMP` can add company profile and earnings context
  - **yfinance** (free, no API key) is always used as fallback when other providers fail or rate-limit
- UI:
  - Dashboard at `/` with broad-scan and watchlist-scan flows

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000)

## API

- `GET /health`
- `GET /api/v1/demo?watchlist=space,uranium`
- `POST /api/v1/scan`
- `POST /api/v1/keywords`

Example: run a watchlist scan:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/scan" \
  -H "Content-Type: application/json" \
  -d '{"watchlist": ["space", "uranium", "data_centers"], "max_articles_per_sector": 4, "max_sectors": 8}'
```

Example: preview generated keywords for a sector:

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/keywords" \
  -H "Content-Type: application/json" \
  -d '{"sectors": ["semiconductors"]}'
```

## Environment variables

- `OPENAI_API_KEY`: optional, enables LLM event extraction
- `NEWSAPI_KEY`: optional, enables live news ingestion
- `FINNHUB_API_KEY`: optional, adds Finnhub market news and live market confirmation
- `POLYGON_API_KEY`: optional, preferred source for richer stock/ETF price and volume confirmation
- `FMP_API_KEY`: optional, adds company profile and earnings context via Financial Modeling Prep
- **yfinance:** always enabled as free fallback for market data and company insights (no API key)
- `OPENAI_MODEL`: default `gpt-4o-mini`
- `PLUTUS_MAX_ARTICLES`: global cap for per-run articles
- `LOG_LEVEL`: `INFO` (default), `DEBUG`, `WARNING`, `ERROR`

## API limits and workarounds

| Provider | Issue | Workaround |
|----------|-------|------------|
| **Polygon** | Free tier: 5 requests/minute | App throttles automatically. Use `max_sectors=4` for faster scans. |
| **NewsAPI** | Free tier: 100 requests/day | App throttles to 5/min. Use `max_sectors=4` to avoid 429. Finnhub used as fallback when NewsAPI fails. |
| **Finnhub** | Free tier: stock/candle may return 403 | Gracefully degrades; market score uses neutral when unavailable. |
| **FMP** | Earnings endpoint returns 402 (paid plan) | Profile data still used; earnings context skipped. |
| **yfinance** | Free fallback | Yahoo Finance via yfinance. No API key. Used when Polygon/Finnhub/FMP fail. |
| **Logs** | httpx logs full URLs (API keys) | httpx/httpcore loggers set to WARNING by default. **Rotate any keys that were exposed.** |

## Next versions

- V2: historical analog lookup + confidence calibration with stored analogs
- V3: personalized signals + alerts + backtesting
