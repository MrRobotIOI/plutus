import asyncio
import json
import logging
import os
import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from starlette.responses import StreamingResponse

from app.config import settings

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("plutus")
# Prevent httpx/httpcore from logging full URLs (exposes API keys)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
from app.event_detector import EventDetector
from app.keywords import KeywordGenerator
from app.market import (
    CompositeMarketDataProvider,
    CompositeMarketInsightProvider,
    FMPMarketInsightProvider,
    FinnhubMarketDataProvider,
    MarketDataProvider,
    MarketInsightProvider,
    NeutralMarketDataProvider,
    NeutralMarketInsightProvider,
    PolygonMarketDataProvider,
    PolygonMarketInsightProvider,
    YFinanceMarketDataProvider,
    YFinanceMarketInsightProvider,
)

_NEUTRAL_MARKET = NeutralMarketDataProvider()
_NEUTRAL_INSIGHT = NeutralMarketInsightProvider()
from app.models import GroupedRunResponse, KeywordsRequest, SectorScanRequest
from app.news import (
    AggregatingNewsProvider,
    DuckDuckGoNewsProvider,
    FinnhubNewsProvider,
    GoogleNewsRssProvider,
    MockNewsProvider,
    NewsApiProvider,
    NewsProvider,
    PooledNewsProvider,
)
from app.scan import run_sector_scan

app = FastAPI(title="plutus", version="0.1.0")

_SCAN_CACHE: dict[tuple[tuple[str, ...], int, int], tuple[GroupedRunResponse, float]] = {}
_SCAN_CACHE_LOCK = asyncio.Lock()
_SCAN_CACHE_INPUTS: dict[tuple[tuple[str, ...], int, int], tuple[list[str], int, int]] = {}
_SCAN_CACHE_REFRESH_IN_PROGRESS: set[tuple[tuple[str, ...], int, int]] = set()
_SCAN_CACHE_REFRESH_TASK: asyncio.Task | None = None

# Precomputed daily scan for homepage (large scan once per 24h)
_DAILY_SCAN_RESULT: GroupedRunResponse | None = None
_DAILY_SCAN_TASK: asyncio.Task | None = None


def _provider_status() -> dict[str, str]:
    """Which services are available vs unavailable (no API key)."""
    status: dict[str, str] = {}
    status["openai"] = "available" if settings.openai_api_key else "unavailable (OPENAI_API_KEY missing)"
    status["newsapi"] = "available" if settings.newsapi_key else "unavailable (NEWSAPI_KEY missing)"
    status["finnhub"] = "available" if settings.finnhub_key else "unavailable (FINNHUB_API_KEY missing)"
    status["polygon"] = "available (POLYGON_API_KEY or MASSIVE_API_KEY)" if settings.polygon_key else "unavailable (POLYGON_API_KEY missing)"
    status["fmp"] = "available" if settings.fmp_key else "unavailable (FMP_API_KEY missing)"
    status["news"] = "live (Google primary + NewsAPI + Finnhub + DuckDuckGo)" if (settings.newsapi_key or settings.finnhub_key) else "live (Google primary + DuckDuckGo)"
    status["events"] = "openai" if settings.openai_api_key else "heuristic (OPENAI_API_KEY missing)"
    status["market"] = "polygon/finnhub" if (settings.polygon_key or settings.finnhub_key) else "yfinance only"
    status["insight"] = "polygon/fmp" if (settings.polygon_key or settings.fmp_key) else "yfinance only"
    return status


ProgressCallback = Callable[[str], Awaitable[None]] | None


@app.on_event("startup")
async def startup():
    global _SCAN_CACHE_REFRESH_TASK, _DAILY_SCAN_TASK
    logger.info("plutus starting (LOG_LEVEL=%s)", LOG_LEVEL)
    s = _provider_status()
    for name in ("openai", "newsapi", "finnhub", "polygon", "fmp"):
        logger.info("  %s: %s", name, s[name])
    for name in ("news", "events", "market", "insight"):
        logger.info("  %s: %s", name, s[name])
    _SCAN_CACHE_REFRESH_TASK = asyncio.create_task(_scan_cache_refresh_loop())
    if settings.env == "prod":
        _DAILY_SCAN_TASK = asyncio.create_task(_daily_scan_loop())
        logger.info("Daily scan: auto-enabled (prod)")
    else:
        logger.info("Daily scan: manual only (dev) — POST /api/v1/daily/trigger to run")


@app.on_event("shutdown")
async def shutdown():
    global _SCAN_CACHE_REFRESH_TASK, _DAILY_SCAN_TASK
    if _SCAN_CACHE_REFRESH_TASK is not None:
        _SCAN_CACHE_REFRESH_TASK.cancel()
        try:
            await _SCAN_CACHE_REFRESH_TASK
        except asyncio.CancelledError:
            pass
        _SCAN_CACHE_REFRESH_TASK = None
    if _DAILY_SCAN_TASK is not None:
        _DAILY_SCAN_TASK.cancel()
        try:
            await _DAILY_SCAN_TASK
        except asyncio.CancelledError:
            pass
        _DAILY_SCAN_TASK = None


@app.middleware("http")
async def log_requests(request, call_next):
    logger.info("%s %s", request.method, request.url.path)
    response = await call_next(request)
    logger.info("%s %s -> %d", request.method, request.url.path, response.status_code)
    return response


def _news_providers() -> list[NewsProvider]:
    """News providers. Google News is primary (first = priority on dedup, larger allocation)."""
    providers: list[NewsProvider] = []
    cache_min = settings.news_cache_minutes
    # Google News RSS: primary source. Free, no API key, query-based, aggregates many publishers.
    providers.append(GoogleNewsRssProvider(cache_minutes=cache_min))
    if settings.newsapi_key:
        providers.append(NewsApiProvider(settings.newsapi_key, cache_minutes=cache_min))
    if settings.finnhub_key:
        providers.append(FinnhubNewsProvider(settings.finnhub_key, cache_minutes=cache_min))
    # DuckDuckGo: supplemental web search, no API key.
    providers.append(DuckDuckGoNewsProvider(cache_minutes=cache_min))
    return providers


def _news_provider(sector_keys: list[str] | None = None) -> NewsProvider:
    providers = _news_providers()
    if not providers:
        return MockNewsProvider()
    if sector_keys:
        return PooledNewsProvider(
            providers, sector_keys, cache_minutes=settings.news_cache_minutes
        )
    if len(providers) > 1:
        return AggregatingNewsProvider(providers)
    return providers[0]


def _market_provider() -> MarketDataProvider:
    providers: list[MarketDataProvider] = []
    if settings.polygon_key:
        providers.append(
            PolygonMarketDataProvider(settings.polygon_key, settings.polygon_base_url)
        )
    providers.append(YFinanceMarketDataProvider())
    if settings.finnhub_key:
        providers.append(FinnhubMarketDataProvider(settings.finnhub_key))
    return CompositeMarketDataProvider(providers) if len(providers) > 1 else providers[0]


def _insight_provider() -> MarketInsightProvider:
    providers: list[MarketInsightProvider] = []
    if settings.polygon_key:
        providers.append(
            PolygonMarketInsightProvider(settings.polygon_key, settings.polygon_base_url)
        )
    providers.append(YFinanceMarketInsightProvider())
    if settings.fmp_key:
        providers.append(FMPMarketInsightProvider(settings.fmp_key))
    return CompositeMarketInsightProvider(providers) if len(providers) > 1 else providers[0]


def _normalize_watchlist(watchlist: list[str]) -> list[str]:
    return [item.strip() for item in watchlist if item and item.strip()]


async def _run_scan_cached(
    watchlist: list[str],
    max_articles_per_sector: int,
    max_sectors: int,
    *,
    on_progress: ProgressCallback = None,
) -> GroupedRunResponse:
    normalized_watchlist = _normalize_watchlist(watchlist)
    watchlist_key = tuple(normalized_watchlist)
    cache_key = (watchlist_key, max_articles_per_sector, max_sectors)
    ttl_seconds = max(0, settings.scan_cache_minutes) * 60
    now = time.time()

    if ttl_seconds > 0:
        async with _SCAN_CACHE_LOCK:
            cached = _SCAN_CACHE.get(cache_key)
            if cached:
                cached_result, cached_at = cached
                age_seconds = now - cached_at
                if age_seconds < ttl_seconds:
                    logger.info(
                        "Scan cache: hit (%d sector groups, %.1f min old)",
                        len(cached_result.sector_groups),
                        age_seconds / 60,
                    )
                    if on_progress is not None:
                        await on_progress(f"Using recent scan ({age_seconds / 60:.1f} min old)")
                    return cached_result
                if cache_key not in _SCAN_CACHE_REFRESH_IN_PROGRESS:
                    _SCAN_CACHE_REFRESH_IN_PROGRESS.add(cache_key)
                    asyncio.create_task(_refresh_scan_cache_entry(cache_key))
                    logger.info("Scan cache: stale entry returned; background refresh started")
                if on_progress is not None:
                    await on_progress(f"Using stale scan ({age_seconds / 60:.1f} min old), refreshing in background")
                return cached_result

    from app.sectors import resolve_sector_keys

    sector_keys = resolve_sector_keys(normalized_watchlist)[:max_sectors]
    provider = _news_provider(sector_keys)
    result = await run_sector_scan(
        watchlist=normalized_watchlist,
        max_articles_per_sector=max_articles_per_sector,
        max_sectors=max_sectors,
        provider=provider,
        detector=EventDetector(settings.openai_api_key, settings.openai_model),
        keyword_generator=KeywordGenerator(settings.openai_api_key, settings.openai_model),
        market_provider=_NEUTRAL_MARKET if settings.fast_scan else _market_provider(),
        insight_provider=_NEUTRAL_INSIGHT if settings.fast_scan else _insight_provider(),
        on_progress=on_progress,
    )

    if ttl_seconds > 0:
        async with _SCAN_CACHE_LOCK:
            _SCAN_CACHE[cache_key] = (result, time.time())
            _SCAN_CACHE_INPUTS[cache_key] = (
                normalized_watchlist,
                max_articles_per_sector,
                max_sectors,
            )
    return result


async def _refresh_scan_cache_entry(cache_key: tuple[tuple[str, ...], int, int]) -> None:
    try:
        async with _SCAN_CACHE_LOCK:
            params = _SCAN_CACHE_INPUTS.get(cache_key)
        if not params:
            return
        watchlist, max_articles_per_sector, max_sectors = params
        normalized_watchlist = _normalize_watchlist(watchlist)
        from app.sectors import resolve_sector_keys

        sector_keys = resolve_sector_keys(normalized_watchlist)[:max_sectors]
        provider = _news_provider(sector_keys)
        refreshed = await run_sector_scan(
            watchlist=normalized_watchlist,
            max_articles_per_sector=max_articles_per_sector,
            max_sectors=max_sectors,
            provider=provider,
            detector=EventDetector(settings.openai_api_key, settings.openai_model),
            keyword_generator=KeywordGenerator(settings.openai_api_key, settings.openai_model),
            market_provider=_NEUTRAL_MARKET if settings.fast_scan else _market_provider(),
            insight_provider=_NEUTRAL_INSIGHT if settings.fast_scan else _insight_provider(),
        )
        async with _SCAN_CACHE_LOCK:
            _SCAN_CACHE[cache_key] = (refreshed, time.time())
        logger.info("Scan cache: background refresh complete")
    except Exception:
        logger.exception("Scan cache: background refresh failed")
    finally:
        async with _SCAN_CACHE_LOCK:
            _SCAN_CACHE_REFRESH_IN_PROGRESS.discard(cache_key)


async def _run_daily_scan() -> None:
    """Run a large precomputed scan for the homepage. Bypasses cache."""
    global _DAILY_SCAN_RESULT
    from app.sectors import DAILY_SCAN_ORDER

    sector_keys = DAILY_SCAN_ORDER[: settings.daily_scan_sectors]
    max_articles = max(settings.daily_scan_articles, 8)

    logger.info("Daily scan: starting (%d sectors, %d articles/sector)", len(sector_keys), max_articles)
    try:
        provider = _news_provider(sector_keys)
        result = await run_sector_scan(
            watchlist=list(sector_keys),
            max_articles_per_sector=max_articles,
            max_sectors=len(sector_keys),
            provider=provider,
            detector=EventDetector(settings.openai_api_key, settings.openai_model),
            keyword_generator=KeywordGenerator(settings.openai_api_key, settings.openai_model),
            market_provider=_NEUTRAL_MARKET if settings.fast_scan else _market_provider(),
            insight_provider=_NEUTRAL_INSIGHT if settings.fast_scan else _insight_provider(),
        )
        _DAILY_SCAN_RESULT = result
        logger.info("Daily scan: complete (%d sector groups, %d sectors)", len(result.sector_groups), len(result.sectors_scanned))
    except Exception:
        logger.exception("Daily scan failed")


async def _daily_scan_loop() -> None:
    """Run daily scan on startup (after delay) and every 24h."""
    interval_seconds = 24 * 60 * 60  # 24 hours
    initial_delay = 10  # Let server start, then fetch
    try:
        await asyncio.sleep(initial_delay)
        await _run_daily_scan()
        while True:
            await asyncio.sleep(interval_seconds)
            await _run_daily_scan()
    except asyncio.CancelledError:
        logger.info("Daily scan loop stopped")
        raise


async def _scan_cache_refresh_loop() -> None:
    interval_seconds = 30
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            ttl_seconds = max(0, settings.scan_cache_minutes) * 60
            if ttl_seconds <= 0:
                continue
            now = time.time()
            stale_keys: list[tuple[tuple[str, ...], int, int]] = []
            async with _SCAN_CACHE_LOCK:
                for cache_key, (_, cached_at) in _SCAN_CACHE.items():
                    if now - cached_at >= ttl_seconds and cache_key not in _SCAN_CACHE_REFRESH_IN_PROGRESS:
                        _SCAN_CACHE_REFRESH_IN_PROGRESS.add(cache_key)
                        stale_keys.append(cache_key)
            for cache_key in stale_keys:
                asyncio.create_task(_refresh_scan_cache_entry(cache_key))
    except asyncio.CancelledError:
        logger.info("Scan cache refresher stopped")
        raise


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt() -> str:
    """Allow crawlers; point to sitemap if site_url is set."""
    base = (settings.site_url or "").rstrip("/")
    sitemap = f"\nSitemap: {base}/sitemap.xml\n" if base else ""
    return f"User-agent: *\nAllow: /{sitemap}"


@app.get("/ads.txt", response_class=PlainTextResponse)
async def ads_txt() -> str:
    """AdSense ads.txt for authorized ad sellers. Required by AdSense."""
    if not settings.adsense_client:
        return "# ads.txt - set ADSENSE_CLIENT_ID to enable"
    # Extract pub-XXXXXXXX from ca-pub-XXXXXXXX
    pub_id = settings.adsense_client
    if pub_id.startswith("ca-"):
        pub_id = "pub-" + pub_id.split("-", 2)[-1]
    return f"google.com, {pub_id}, DIRECT, f08c47fec0942fa0\n"


@app.get("/sitemap.xml", response_class=Response)
async def sitemap_xml() -> Response:
    """Sitemap for search engines."""
    base = (settings.site_url or "https://example.com").rstrip("/")
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>{base}/</loc><changefreq>daily</changefreq><priority>1.0</priority></url>
</urlset>'''
    return Response(content=xml, media_type="application/xml")


@app.get("/api/v1/daily", response_model=GroupedRunResponse | None)
async def get_daily_scan() -> GroupedRunResponse | None:
    """Precomputed daily scan for homepage. Large scan runs once per 24h in prod, or manually in dev."""
    return _DAILY_SCAN_RESULT


@app.post("/api/v1/daily/trigger")
async def trigger_daily_scan() -> dict[str, str]:
    """Manually trigger the daily scan. Useful in dev (prod runs it automatically)."""
    await _run_daily_scan()
    return {"status": "ok", "message": "Daily scan completed"}


@app.get("/api/v1/status")
async def provider_status() -> dict[str, str]:
    """Report which API keys are configured. Call before scans to see what data sources are active."""
    return _provider_status()


@app.post("/api/v1/keywords")
async def generate_keywords(payload: KeywordsRequest) -> dict[str, str]:
    kw_gen = KeywordGenerator(settings.openai_api_key, settings.openai_model)
    if not payload.sectors:
        return {"query": "", "sectors": ""}
    sector_key = payload.sectors[0]
    from app.keywords import sector_from_value

    sector = sector_from_value(sector_key)
    if sector is None:
        return {"query": sector_key, "sectors": sector_key}
    query = await kw_gen.generate_for_sector(sector)
    return {"query": query, "sectors": sector.display_name}


@app.post("/api/v1/scan", response_model=GroupedRunResponse)
async def run_scan(payload: SectorScanRequest) -> GroupedRunResponse:
    logger.info("Scan started: watchlist=%s max_articles_per_sector=%s max_sectors=%s", payload.watchlist, payload.max_articles_per_sector, payload.max_sectors)
    result = await _run_scan_cached(
        watchlist=payload.watchlist,
        max_articles_per_sector=min(payload.max_articles_per_sector, settings.plutus_max_articles),
        max_sectors=payload.max_sectors,
    )
    logger.info("Scan completed: %d sector groups from %d sectors scanned", len(result.sector_groups), len(result.sectors_scanned))
    return result

@app.get("/api/v1/demo", response_model=GroupedRunResponse)
async def run_demo(watchlist: str | None = None) -> GroupedRunResponse:
    watchlist_items = [item.strip() for item in watchlist.split(",") if item.strip()] if watchlist else []
    return await run_scan(
        SectorScanRequest(
            watchlist=watchlist_items,
            max_articles_per_sector=12,
            max_sectors=12,
        )
    )


@app.get("/api/v1/scan/stream")
async def scan_stream(watchlist: str | None = None):
    """SSE endpoint: streams progress events then a final 'result' event with the JSON payload."""
    watchlist_items = [item.strip() for item in watchlist.split(",") if item.strip()] if watchlist else []
    progress_queue: asyncio.Queue[str] = asyncio.Queue()

    async def on_progress(msg: str) -> None:
        await progress_queue.put(msg)

    async def generate():
        result_holder: list[GroupedRunResponse] = []

        async def do_scan():
            r = await _run_scan_cached(
                watchlist=watchlist_items,
                max_articles_per_sector=min(
                    settings.fast_scan_articles if settings.fast_scan else settings.default_max_articles,
                    settings.plutus_max_articles,
                ),
                max_sectors=settings.fast_scan_sectors if settings.fast_scan else settings.default_max_sectors,
                on_progress=on_progress,
            )
            result_holder.append(r)
            await progress_queue.put(None)  # sentinel

        task = asyncio.create_task(do_scan())
        try:
            while True:
                msg = await progress_queue.get()
                if msg is None:
                    break
                yield f"event: progress\ndata: {json.dumps({'message': msg})}\n\n"
            await task
            if result_holder:
                result = result_holder[0]
                logger.info("Scan completed: %d sector groups from %d sectors scanned", len(result.sector_groups), len(result.sectors_scanned))
                yield f"event: result\ndata: {result.model_dump_json()}\n\n"
        except Exception as e:
            logger.exception("SSE scan error")
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/", response_class=HTMLResponse)
async def home() -> str:
    from jinja2 import Template
    return Template(DASHBOARD_HTML).render(
        stripe_checkout_url=settings.stripe_checkout_url or "#",
        site_url=settings.site_url or "",
        og_image_url=settings.og_image_url or "",
        page_title="Stock Market AI | Plutus",
        page_description="AI-powered sector discovery for macro and niche themes. Scan markets, detect events, and get trade ideas from news and market data.",
        adsense_client=settings.adsense_client or "",
        adsense_banner_slot=settings.adsense_banner_slot or "",
        adsense_sidebar_slot=settings.adsense_sidebar_slot or "",
        subscription_enabled=settings.subscription_enabled,
    )


DASHBOARD_HTML = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{{ page_title }}</title>
<meta name="description" content="{{ page_description }}"/>
{% if site_url %}<link rel="canonical" href="{{ site_url }}"/>{% endif %}
<meta property="og:type" content="website"/>
<meta property="og:title" content="{{ page_title }}"/>
<meta property="og:description" content="{{ page_description }}"/>
{% if site_url %}<meta property="og:url" content="{{ site_url }}"/>{% endif %}
{% if og_image_url %}<meta property="og:image" content="{{ og_image_url }}"/>{% endif %}
<meta property="og:site_name" content="Plutus"/>
<meta name="twitter:card" content="summary_large_image"/>
<meta name="twitter:title" content="{{ page_title }}"/>
<meta name="twitter:description" content="{{ page_description }}"/>
{% if og_image_url %}<meta name="twitter:image" content="{{ og_image_url }}"/>{% endif %}
{% if adsense_client %}
<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={{ adsense_client }}" crossorigin="anonymous"></script>
{% endif %}
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet"/>
<style>
:root{--bg:#06090e;--bg2:#0a0f17;--surface:#111827;--surface2:#1a2332;--surface3:#243044;--border:#2d3a4f;--accent:#7c3aed;--accent2:#a78bfa;--accent3:#c4b5fd;--green:#10b981;--red:#ef4444;--amber:#f59e0b;--text:#f1f5f9;--text2:#94a3b8;--text3:#64748b;--radius:14px;--radius-lg:20px;--shadow:0 8px 32px rgba(0,0,0,.5);--glow:0 0 40px rgba(124,58,237,.15)}
[data-theme="light"]{--bg:#f8fafc;--bg2:#f1f5f9;--surface:#ffffff;--surface2:#f1f5f9;--surface3:#e2e8f0;--border:#cbd5e1;--accent:#7c3aed;--accent2:#6d28d9;--accent3:#5b21b6;--green:#059669;--red:#dc2626;--amber:#d97706;--text:#0f172a;--text2:#475569;--text3:#64748b;--shadow:0 8px 32px rgba(0,0,0,.08);--glow:0 0 40px rgba(124,58,237,.08)}
*{margin:0;padding:0;box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{font-family:'Outfit',sans-serif;background:var(--bg);color:var(--text);min-height:100vh;position:relative;overflow-x:hidden}
body::before{content:"";position:fixed;inset:0;background:radial-gradient(ellipse 80% 50% at 50% -20%,rgba(124,58,237,.12),transparent),radial-gradient(ellipse 60% 40% at 100% 50%,rgba(16,185,129,.06),transparent),radial-gradient(ellipse 60% 40% at 0% 80%,rgba(245,158,11,.05),transparent);pointer-events:none;z-index:0}
body::after{content:"";position:fixed;inset:0;background-image:linear-gradient(rgba(255,255,255,.02) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.02) 1px,transparent 1px);background-size:60px 60px;pointer-events:none;z-index:0;opacity:.5}
[data-theme="light"] body::before{background:radial-gradient(ellipse 80% 50% at 50% -20%,rgba(124,58,237,.06),transparent),radial-gradient(ellipse 60% 40% at 100% 50%,rgba(16,185,129,.04),transparent),radial-gradient(ellipse 60% 40% at 0% 80%,rgba(245,158,11,.03),transparent)}
[data-theme="light"] body::after{background-image:linear-gradient(rgba(0,0,0,.03) 1px,transparent 1px),linear-gradient(90deg,rgba(0,0,0,.03) 1px,transparent 1px);opacity:.6}
.container{max-width:1400px;margin:0 auto;padding:1.5rem;position:relative;z-index:1}
header{display:flex;align-items:center;justify-content:space-between;margin-bottom:2rem;flex-wrap:wrap;gap:1rem;padding:1rem 0}
header h1{font-size:2rem;font-weight:800;letter-spacing:-.02em;background:linear-gradient(135deg,var(--text) 0%,var(--accent2) 50%,var(--accent3) 100%);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
header h1 span{background:linear-gradient(135deg,var(--accent2),var(--accent3));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.brand-subtitle{font-size:.55em;font-weight:500;color:var(--text2);margin-left:.4rem;vertical-align:middle}
.status-bar{display:flex;gap:0.5rem;flex-wrap:wrap}
.status-pill{font-size:.7rem;padding:.25rem .6rem;border-radius:20px;background:var(--surface2);color:var(--text2);border:1px solid var(--border)}
.status-pill.ok{border-color:var(--green);color:var(--green)}
.status-pill.warn{border-color:var(--amber);color:var(--amber)}
.controls{display:flex;gap:1rem;align-items:center;margin:0 auto 1.5rem;flex-wrap:wrap;max-width:900px}
.controls input{background:linear-gradient(135deg,var(--surface) 0%,var(--surface2) 100%);border:1px solid var(--border);border-radius:var(--radius-lg);padding:.85rem 1.25rem;color:var(--text);font-size:.9rem;width:380px;outline:none;transition:all .25s;font-family:inherit;box-shadow:inset 0 2px 8px rgba(0,0,0,.2)}
.controls input:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(124,58,237,.2),inset 0 2px 8px rgba(0,0,0,.2)}
.controls input::placeholder{color:var(--text3)}
.btn{padding:.75rem 1.5rem;border:none;border-radius:var(--radius-lg);font-size:.9rem;font-weight:600;cursor:pointer;transition:all .2s;font-family:inherit}
.btn-primary{background:linear-gradient(135deg,var(--accent) 0%,#9333ea 100%);color:#fff;box-shadow:0 4px 16px rgba(124,58,237,.4)}
.btn-primary:hover{transform:translateY(-2px);box-shadow:0 6px 24px rgba(124,58,237,.5)}
.btn-primary:disabled{opacity:.5;cursor:not-allowed;transform:none}
.btn-gundam{position:relative;background:linear-gradient(135deg,var(--accent) 0%,#9333ea 100%);color:#fff;border:none;border-radius:var(--radius-lg);padding:.85rem 1.75rem;font-size:.9rem;font-weight:700;letter-spacing:.08em;text-transform:uppercase;cursor:pointer;transition:all .25s;font-family:inherit;box-shadow:0 4px 16px rgba(124,58,237,.35)}
.btn-gundam:hover{transform:translateY(-2px);box-shadow:0 6px 24px rgba(124,58,237,.45)}
.btn-gundam:disabled{opacity:.5;cursor:not-allowed;transform:none}
.btn-gundam:disabled:hover{box-shadow:0 4px 16px rgba(124,58,237,.35)}
.scan-status{font-size:.85rem;color:var(--text2);margin:0 auto 1rem;min-height:1.2rem;font-weight:500;max-width:900px}
.layout{max-width:900px;width:100%;margin:0 auto}
.view-toggle{display:flex;gap:.25rem;margin-bottom:1rem}
.view-toggle button{font-size:.75rem;font-weight:600;padding:.4rem .75rem;border-radius:8px;border:1px solid var(--border);background:var(--surface2);color:var(--text2);cursor:pointer;transition:all .2s;font-family:inherit}
.view-toggle button:hover{color:var(--text);border-color:var(--accent)}
.view-toggle button.active{background:var(--accent);color:#fff;border-color:var(--accent)}
.tag-cloud{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:.6rem 1rem;padding:2rem 1rem;min-height:200px}
.tag-cloud-tag{display:inline-block;padding:.35rem .85rem;border-radius:10px;cursor:pointer;transition:all .25s;font-weight:600;text-decoration:none;border:1px solid transparent;line-height:1.3}
.tag-cloud-tag:hover{transform:scale(1.08);box-shadow:0 4px 16px rgba(0,0,0,.3)}
.tag-cloud-tag.active{box-shadow:0 0 0 2px var(--accent);border-color:var(--accent)}
.tag-cloud-hint{font-size:.72rem;color:var(--text3);text-align:center;margin-top:.75rem;font-weight:500}
.sidebar-label{font-size:.7rem;text-transform:uppercase;letter-spacing:.12em;color:var(--accent2);margin-bottom:1rem;font-weight:600}
.sector-card{background:linear-gradient(145deg,var(--surface) 0%,var(--surface2) 100%);border:1px solid var(--border);border-radius:var(--radius-lg);padding:1.25rem;margin-bottom:0;cursor:pointer;transition:all .25s;box-shadow:0 4px 20px rgba(0,0,0,.2);position:relative;overflow:hidden}
.sector-card::before{content:"";position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--accent),transparent);opacity:0;transition:opacity .25s}
.sector-card:hover{border-color:var(--accent);box-shadow:0 8px 32px rgba(124,58,237,.15),var(--glow);transform:translateY(-2px)}
.sector-card:hover::before{opacity:1}
.sector-card.active{border-color:var(--accent);box-shadow:0 0 0 2px rgba(124,58,237,.3),0 8px 32px rgba(0,0,0,.3);background:linear-gradient(145deg,var(--surface2) 0%,var(--surface3) 100%);border-radius:var(--radius-lg) var(--radius-lg) 0 0;margin-bottom:0}
.sector-card.active::before{opacity:1}
.sector-card h3{font-size:1.05rem;font-weight:700;margin-bottom:.35rem;letter-spacing:-.01em}
.sector-card .meta{font-size:.78rem;color:var(--text2);display:flex;gap:.75rem;flex-wrap:wrap;margin-bottom:.5rem}
.sector-card .chevron{float:right;transition:transform .25s;color:var(--text3);font-size:.9rem;margin-top:.15rem}
.sector-card.active .chevron{transform:rotate(180deg);color:var(--accent2)}
.sector-item{margin-bottom:1rem}
.sector-detail-inline{background:linear-gradient(180deg,var(--surface2) 0%,var(--surface) 100%);border:1px solid var(--accent);border-top:none;border-radius:0 0 var(--radius-lg) var(--radius-lg);padding:1.5rem;overflow:hidden;animation:slideDown .3s ease-out;box-shadow:inset 0 4px 20px rgba(0,0,0,.2)}
@keyframes slideDown{from{opacity:0;max-height:0;padding:0 1.5rem}to{opacity:1;max-height:2000px;padding:1.5rem}}
.score-bar{height:6px;border-radius:3px;background:var(--surface3);overflow:hidden;margin:.6rem 0;box-shadow:inset 0 1px 3px rgba(0,0,0,.3)}
.score-bar-fill{height:100%;border-radius:3px;transition:width .4s ease-out;box-shadow:0 0 12px currentColor}
.score-row{display:flex;justify-content:space-between;align-items:center;font-size:.78rem}
.score-label{color:var(--text2);font-weight:500}
.badge{display:inline-block;font-size:.68rem;font-weight:700;padding:.2rem .6rem;border-radius:10px;text-transform:uppercase;letter-spacing:.06em}
.badge-low{background:linear-gradient(135deg,rgba(239,68,68,.25),rgba(239,68,68,.1));color:#fca5a5;border:1px solid rgba(239,68,68,.3)}
.badge-medium{background:linear-gradient(135deg,rgba(245,158,11,.25),rgba(245,158,11,.1));color:#fcd34d;border:1px solid rgba(245,158,11,.3)}
.badge-high{background:linear-gradient(135deg,rgba(16,185,129,.25),rgba(16,185,129,.1));color:#6ee7b7;border:1px solid rgba(16,185,129,.3)}
.badge-weak{background:rgba(100,116,139,.2);color:var(--text3);border:1px solid rgba(100,116,139,.2)}
[data-theme="light"] .badge-low{color:#b91c1c}
[data-theme="light"] .badge-medium{color:#b45309}
[data-theme="light"] .badge-high{color:#047857}
.detail-header{margin-bottom:1.25rem}
.detail-header h2{font-size:1.15rem;font-weight:700;margin-bottom:.5rem;letter-spacing:-.01em}
.ideas-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:1rem;margin:1rem 0}
.idea-chip{background:linear-gradient(145deg,var(--surface2) 0%,var(--surface3) 100%);border:1px solid var(--border);border-radius:var(--radius);padding:1rem;font-size:.82rem;transition:all .2s;box-shadow:0 2px 12px rgba(0,0,0,.15)}
.idea-chip:hover{border-color:var(--accent);transform:translateY(-1px);box-shadow:0 4px 20px rgba(124,58,237,.1)}
.idea-action-row{display:flex;flex-direction:column;gap:.5rem;margin-bottom:.4rem}
.idea-action-row .action-badge{align-self:flex-start}
.action-badge{font-weight:700;font-size:.72rem;letter-spacing:.05em;padding:.25rem .6rem;border-radius:8px}
.action-badge.buy{background:linear-gradient(135deg,rgba(16,185,129,.3),rgba(16,185,129,.15));color:#6ee7b7;border:1px solid rgba(16,185,129,.4)}
.action-badge.avoid{background:linear-gradient(135deg,rgba(239,68,68,.25),rgba(239,68,68,.1));color:#fca5a5;border:1px solid rgba(239,68,68,.3)}
[data-theme="light"] .action-badge.buy{color:#047857}
[data-theme="light"] .action-badge.avoid{color:#b91c1c}
.idea-chip .symbol{font-weight:700;color:var(--text);font-family:'JetBrains Mono',monospace}
.symbols-row{display:flex;flex-wrap:wrap;gap:.35rem;align-items:center}
.symbol-box{display:inline-block;font-family:'JetBrains Mono',monospace;font-weight:600;font-size:.75rem;padding:.2rem .5rem;border-radius:6px}
.idea-chip.buy .symbol-box{background:rgba(16,185,129,.2);border:1px solid rgba(16,185,129,.4);color:#6ee7b7}
.idea-chip.avoid .symbol-box{background:rgba(239,68,68,.15);border:1px solid rgba(239,68,68,.35);color:#fca5a5}
[data-theme="light"] .idea-chip.buy .symbol-box{color:#047857;background:rgba(16,185,129,.15);border-color:rgba(16,185,129,.35)}
[data-theme="light"] .idea-chip.avoid .symbol-box{color:#b91c1c;background:rgba(239,68,68,.12);border-color:rgba(239,68,68,.3)}
.symbol-more{font-size:.72rem;color:var(--text3);margin-left:.15rem}
.idea-how{font-size:.74rem;color:var(--text3);margin-bottom:.4rem;line-height:1.4}
.idea-chip .rationale{color:var(--text2);font-size:.78rem;line-height:1.5}
.idea-chip .idea-insights{font-size:.7rem;color:var(--text3);margin-top:.5rem;line-height:1.5}
.ideas-note{font-size:.82rem;color:var(--text3);font-style:italic;margin:.5rem 0}
.cluster-section{margin-bottom:1.5rem;padding:1rem;background:rgba(0,0,0,.15);border-radius:var(--radius);border:1px solid rgba(255,255,255,.05)}
[data-theme="light"] .cluster-section{background:rgba(0,0,0,.04);border-color:rgba(0,0,0,.08)}
.cluster-header{display:flex;align-items:center;gap:.6rem;margin-bottom:1rem;padding-bottom:.75rem;border-bottom:1px solid var(--border)}
.cluster-header h3{font-size:1rem;font-weight:700;background:linear-gradient(90deg,var(--accent2),var(--accent3));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.cluster-header .count{font-size:.72rem;color:var(--text3);font-weight:500}
.signal-card{background:linear-gradient(145deg,var(--surface) 0%,var(--surface2) 100%);border:1px solid var(--border);border-radius:var(--radius);padding:1.25rem;margin-bottom:1rem;transition:all .2s;box-shadow:0 2px 16px rgba(0,0,0,.2)}
.signal-card:hover{border-color:rgba(124,58,237,.4);box-shadow:0 4px 24px rgba(0,0,0,.25)}
.signal-card h4{font-size:.9rem;font-weight:700;margin-bottom:.4rem;line-height:1.3;word-wrap:break-word;overflow-wrap:break-word}
.signal-card h4 a{color:var(--accent2);text-decoration:none;transition:color .2s;word-break:break-word}
.signal-card h4 a:hover{color:var(--accent3);text-decoration:underline}
.signal-source{font-size:.72rem;color:var(--text3);margin-bottom:.5rem;font-family:'JetBrains Mono',monospace}
.signal-summary{font-size:.84rem;color:var(--text2);margin-bottom:.85rem;line-height:1.6;background:linear-gradient(135deg,var(--surface2) 0%,var(--surface3) 100%);padding:.85rem 1rem;border-radius:10px;border-left:4px solid var(--accent);box-shadow:inset 0 1px 3px rgba(0,0,0,.2)}
.score-explainer{margin:1rem 0}
.score-factor{margin-bottom:.75rem}
.score-factor:last-child{margin-bottom:0}
.factor-bar-wrap{height:8px;border-radius:4px;background:var(--surface3);overflow:hidden;margin-bottom:.3rem;box-shadow:inset 0 1px 3px rgba(0,0,0,.3)}
.factor-bar{display:block;height:100%;border-radius:4px;min-width:2px;transition:width .4s ease-out}
.factor-label{font-size:.82rem;font-weight:700;color:var(--text);display:block}
.factor-desc{font-size:.72rem;color:var(--text3);display:block;margin-top:.15rem}
.confidence-row{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:.5rem;margin-top:.6rem}
.confidence-text{font-size:.82rem;color:var(--text2);line-height:1.4;font-weight:500}
.risk-reward-row{margin-top:.4rem;font-size:.78rem}
.risk-pill{font-size:.68rem;font-weight:700;padding:.25rem .6rem;border-radius:10px;cursor:pointer;transition:all .2s}
.risk-pill:hover{opacity:.9;transform:scale(1.05)}
.risk-pill.risk-low{background:linear-gradient(135deg,rgba(16,185,129,.25),rgba(16,185,129,.1));color:#6ee7b7;border:1px solid rgba(16,185,129,.3)}
.risk-pill.risk-medium{background:linear-gradient(135deg,rgba(245,158,11,.2),rgba(245,158,11,.08));color:#fcd34d;border:1px solid rgba(245,158,11,.25)}
.risk-pill.risk-high{background:linear-gradient(135deg,rgba(239,68,68,.2),rgba(239,68,68,.08));color:#fca5a5;border:1px solid rgba(239,68,68,.25)}
[data-theme="light"] .risk-pill.risk-low{color:#047857}
[data-theme="light"] .risk-pill.risk-medium{color:#b45309}
[data-theme="light"] .risk-pill.risk-high{color:#b91c1c}
.homework-toggle{cursor:pointer;font-size:.78rem;color:var(--accent2);text-decoration:underline;margin-top:.5rem;display:inline-block;font-weight:600;transition:color .2s}
.homework-toggle:hover{color:var(--accent3)}
.homework-detail{display:none;margin-top:1rem;padding-top:1rem;border-top:1px solid var(--border)}
.homework-detail.open{display:block}
.score-graph{display:flex;align-items:flex-end;gap:.6rem;height:110px;margin-bottom:1.25rem}
.score-graph-bar{flex:1;min-width:50px;height:110px;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;gap:.3rem}
.score-graph-bar .bar{width:65%;min-height:6px;border-radius:6px 6px 0 0;transition:height .4s ease-out}
.score-graph-bar .lbl{font-size:.68rem;color:var(--text3);text-align:center;font-weight:500}
.homework-section{margin-bottom:1.25rem}
.homework-section h5{font-size:.84rem;font-weight:700;margin-bottom:.4rem;color:var(--text)}
.homework-section p{font-size:.8rem;color:var(--text2);line-height:1.55}
.notes-box{font-size:.78rem;color:var(--text2);background:var(--surface2);border-radius:10px;padding:.6rem .9rem;margin-top:.5rem;line-height:1.5;border:1px solid var(--border)}
.empty-state{text-align:center;padding:5rem 2.5rem;color:var(--text3);background:linear-gradient(145deg,var(--surface) 0%,var(--surface2) 100%);border-radius:var(--radius-lg);border:1px dashed var(--border);margin:1rem 0}
.empty-state p{font-size:.95rem;max-width:420px;margin:0 auto;line-height:1.6;transition:opacity .15s;font-weight:500}
.spinner{display:inline-block;width:18px;height:18px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .7s linear infinite;margin-right:.5rem;vertical-align:middle}
@keyframes spin{to{transform:rotate(360deg)}}
.hero{margin-bottom:2rem;padding:2rem 0;text-align:center;max-width:720px;margin-left:auto;margin-right:auto}
.hero h2{font-size:1.5rem;font-weight:700;line-height:1.35;color:var(--text);margin-bottom:1rem;letter-spacing:-.02em}
.hero p{font-size:1rem;color:var(--text2);line-height:1.65;margin-bottom:.75rem}
.hero .tagline{font-size:.9rem;color:var(--text3);font-weight:500}
.disclaimer-bar{color:var(--text3);margin-top:3rem;padding:.75rem 1.5rem;font-size:.7rem;text-align:center;line-height:1.5;letter-spacing:.03em;opacity:.85;border-top:1px solid var(--border)}
.ad-slot{background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius-lg);display:flex;align-items:center;justify-content:center;color:var(--text3);font-size:.7rem;letter-spacing:.06em;overflow:hidden}
.ad-banner{width:100%;max-width:728px;height:90px;margin:0 auto 1.5rem}
.ad-sidebar{min-height:250px;width:100%;max-width:300px}
.subscribe-btn{background:linear-gradient(135deg,var(--accent) 0%,#9333ea 100%);color:#fff;padding:.5rem 1.1rem;border-radius:var(--radius-lg);font-size:.85rem;font-weight:700;cursor:pointer;border:none;transition:all .2s;box-shadow:0 4px 16px rgba(124,58,237,.35)}
.subscribe-btn:hover{transform:translateY(-2px);box-shadow:0 6px 24px rgba(124,58,237,.45)}
.pro-badge{font-size:.72rem;padding:.25rem .6rem;border-radius:10px;background:linear-gradient(135deg,rgba(16,185,129,.3),rgba(16,185,129,.15));color:#6ee7b7;font-weight:700;cursor:pointer;border:1px solid rgba(16,185,129,.4)}
[data-theme="light"] .pro-badge{color:#047857}
.theme-toggle{background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);padding:.4rem .65rem;cursor:pointer;color:var(--text2);font-size:1.1rem;transition:all .2s;line-height:1}
.theme-toggle:hover{color:var(--text);border-color:var(--accent)}
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.8);backdrop-filter:blur(4px);display:flex;align-items:center;justify-content:center;z-index:1000;opacity:0;visibility:hidden;transition:all .25s}
.modal-overlay.open{opacity:1;visibility:visible}
.modal{background:linear-gradient(180deg,var(--surface) 0%,var(--surface2) 100%);border:1px solid var(--border);border-radius:var(--radius-lg);padding:2rem;max-width:440px;width:90%;box-shadow:0 24px 64px rgba(0,0,0,.5),0 0 0 1px rgba(255,255,255,.05)}
.modal h2{margin-bottom:1rem;font-size:1.35rem;font-weight:800;background:linear-gradient(90deg,var(--text),var(--accent2));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.modal-close{float:right;cursor:pointer;color:var(--text3);font-size:1.4rem;line-height:1;transition:color .2s}
.modal-close:hover{color:var(--text)}
.plan-card{border:1px solid var(--border);border-radius:var(--radius);padding:1.35rem;margin-bottom:1rem;cursor:pointer;transition:all .2s;background:var(--surface2)}
.plan-card:hover{border-color:var(--accent);transform:translateY(-2px);box-shadow:0 8px 24px rgba(124,58,237,.15)}
.plan-card.featured{border-color:var(--accent);box-shadow:0 0 0 2px rgba(124,58,237,.25),0 4px 20px rgba(0,0,0,.2)}
.plan-name{font-weight:800;font-size:1.1rem;margin-bottom:.3rem}
.plan-price{font-size:1.6rem;font-weight:800;background:linear-gradient(90deg,var(--accent2),var(--accent3));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;margin:.5rem 0}
.plan-features{font-size:.85rem;color:var(--text2);list-style:none;padding:0}
.plan-features li{margin:.4rem 0;padding-left:1.25rem;position:relative}
.plan-features li:before{content:"✓";color:var(--green);position:absolute;left:0;font-weight:700}
.page-layout{display:block}
.page-main{width:100%;max-width:100%}
.page-sidebar{width:100%;max-width:728px;margin:2rem auto 0;display:flex;justify-content:center}
.ad-sidebar{min-height:250px;max-width:300px;margin:0 auto}
@media(max-width:640px){
  .container{padding:1rem;padding-bottom:2rem;overflow-x:hidden}
  .hero{padding:1.25rem 0;margin-bottom:1.5rem}
  .hero h2{font-size:1.2rem;margin-bottom:.75rem}
  .hero p{font-size:.9rem}
  .hero .tagline{font-size:.8rem}
  header{padding:.5rem 0;margin-bottom:1.25rem;flex-direction:column;align-items:flex-start}
  header h1{font-size:1.35rem;line-height:1.3;word-break:break-word}
  .brand-subtitle{font-size:.5em;margin-left:.25rem}
  .subscribe-btn,.pro-badge{font-size:.8rem;padding:.4rem .9rem}
  .controls{flex-direction:column;align-items:stretch;gap:.75rem;margin-bottom:1rem}
  .controls input{width:100%;max-width:100%;padding:.75rem 1rem;font-size:16px}
  .btn-gundam{width:100%;padding:.85rem 1rem;letter-spacing:.08em;font-size:.85rem}
  .ad-banner{height:70px;margin-bottom:1rem}
  .layout{max-width:100%}
  .sector-card{padding:1rem;border-radius:var(--radius)}
  .sector-card.active{border-radius:var(--radius) var(--radius) 0 0}
  .sector-card h3{font-size:.95rem}
  .sector-detail-inline{padding:1rem;border-radius:0 0 var(--radius) var(--radius)}
  .ideas-grid{grid-template-columns:1fr;gap:.75rem;margin:.75rem 0}
  .idea-chip{padding:.85rem}
  .cluster-section{padding:.75rem;margin-bottom:1rem}
  .cluster-header{flex-wrap:wrap;gap:.4rem}
  .signal-card{padding:1rem;margin-bottom:.85rem}
  .signal-summary{padding:.7rem .85rem;font-size:.82rem}
  .score-graph{height:90px;gap:.4rem;margin-bottom:1rem}
  .score-graph-bar{min-width:36px}
  .score-graph-bar .lbl{font-size:.6rem}
  .confidence-row{flex-direction:column;align-items:flex-start;gap:.4rem}
  .empty-state{padding:2.5rem 1.5rem;margin:.75rem 0}
  .empty-state p{font-size:.88rem}
  .modal{padding:1.5rem;margin:1rem;max-height:90vh;overflow-y:auto}
  .modal h2{font-size:1.15rem}
  .plan-card{padding:1rem}
  .plan-price{font-size:1.35rem}
  .disclaimer-bar{padding:.6rem 1rem;font-size:.65rem;margin-top:2rem}
.page-sidebar{margin-top:1.5rem}
}
</style>
</head>
<body>
<script>
(function(){
  const k="plutus_theme";
  const v=localStorage.getItem(k)||"light";
  document.documentElement.setAttribute("data-theme",v);
})();
</script>
<div class="container">
  <header style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:1rem">
    <h1><span>Stock Market AI</span> <small class="brand-subtitle">Plutus</small></h1>
    <div style="display:flex;align-items:center;gap:.5rem">
      <button id="themeToggle" class="theme-toggle" onclick="toggleTheme()" title="Toggle light/dark mode" aria-label="Toggle theme">☀</button>
      {% if subscription_enabled %}<span id="proBadge" class="pro-badge" style="display:none" onclick="openSubscribeModal()" title="Manage subscription">Pro</span>
      <button id="subscribeBtn" class="subscribe-btn" onclick="openSubscribeModal()">Subscribe</button>{% endif %}
    </div>
  </header>
  <section class="hero">
    <h2>AI-powered macro research that turns world news into actionable market signals</h2>
    <p>Plutus scans hundreds of sectors, ingests global news from trusted sources, and uses AI to detect macro events, then maps them to sectors and trade ideas with transparent scoring.</p>
    <p class="tagline">Research-grade signal discovery.</p>
  </section>
  <div id="adBanner" class="ad-slot ad-banner">
    {% if adsense_client and adsense_banner_slot %}
    <ins class="adsbygoogle" style="display:block" data-ad-client="{{ adsense_client }}" data-ad-slot="{{ adsense_banner_slot }}" data-ad-format="horizontal" data-full-width-responsive="true"></ins>
    <script>(adsbygoogle=window.adsbygoogle||[]).push({})</script>
    {% else %}
    <span>Advertisement</span>
    {% endif %}
  </div>
  <div class="controls">
    <input id="watchlist" type="text" placeholder="Any topic: crypto, video games, AI, space, semiconductors..." onkeydown="if(event.key==='Enter')runScan(false)"/>
    <button class="btn btn-gundam" id="scanBtn" onclick="document.getElementById('scanBtn').textContent==='Cancel'?runScan(true):runScan(false)">Scan Markets</button>
  </div>
  <div id="scanStatus" class="scan-status"></div>
  <div class="page-layout">
    <div class="page-main">
      <div class="layout">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.75rem;margin-bottom:.5rem">
          <div class="sidebar-label" style="margin-bottom:0">Sectors with signals</div>
          <div class="view-toggle" id="viewToggle" style="display:none">
            <button id="btnList" onclick="setViewMode('list')">List</button>
            <button id="btnTagCloud" onclick="setViewMode('tagcloud')">Tag cloud</button>
          </div>
        </div>
        <div id="sectorList">
          <div class="empty-state">
            <p>Scan 200+ sectors for macro events and trading signals. Enter a topic above or run a broad scan to get started.</p>
            <p style="margin-top:.5rem;font-size:.8rem">A daily scan runs automatically in production — results appear when ready.</p>
          </div>
        </div>
      </div>
    </div>
    <aside id="adSidebar" class="page-sidebar">
      <div class="ad-slot ad-sidebar">
        {% if adsense_client and adsense_sidebar_slot %}
        <ins class="adsbygoogle" style="display:block" data-ad-client="{{ adsense_client }}" data-ad-slot="{{ adsense_sidebar_slot }}" data-ad-format="rectangle" data-full-width-responsive="true"></ins>
        <script>(adsbygoogle=window.adsbygoogle||[]).push({})</script>
        {% else %}
        <span>Advertisement</span>
        {% endif %}
      </div>
    </aside>
  </div>
</div>
{% if subscription_enabled %}
<div id="subscribeModal" class="modal-overlay" onclick="if(event.target===this)closeSubscribeModal()">
  <div class="modal">
    <span class="modal-close" onclick="closeSubscribeModal()">&times;</span>
    <h2>Upgrade to Pro</h2>
    <p style="font-size:.9rem;color:var(--text2);margin-bottom:1.5rem">Remove ads and unlock premium features.</p>
    <div class="plan-card featured" onclick="goToCheckout('pro')">
      <div class="plan-name">Pro</div>
      <div class="plan-price">$9.99<span style="font-size:.8rem;font-weight:400;color:var(--text2)">/month</span></div>
      <ul class="plan-features">
        <li>Ad-free experience</li>
        <li>Unlimited scans</li>
      </ul>
    </div>
    <div class="plan-card" onclick="goToCheckout('annual')">
      <div class="plan-name">Pro Annual</div>
      <div class="plan-price">$99<span style="font-size:.8rem;font-weight:400;color:var(--text2)">/year</span></div>
      <ul class="plan-features">
        <li>Everything in Pro</li>
        <li>Save 17%</li>
      </ul>
    </div>
    <p id="cancelOption" style="display:none;margin-top:1rem;font-size:.8rem">
      <a href="#" onclick="setSubscribed(false);closeSubscribeModal();return false" style="color:var(--text3)">Cancel subscription</a>
    </p>
  </div>
</div>
{% endif %}
<div class="disclaimer-bar">Not financial advice. For informational purposes only. Past performance does not guarantee future results. Do your own research.</div>
<script>
const STRIPE_CHECKOUT_URL = "{{ stripe_checkout_url }}";
const SUBSCRIPTION_ENABLED = {{ "true" if subscription_enabled else "false" }};
const SUBSCRIPTION_KEY = "plutus_subscribed";
const THEME_KEY = "plutus_theme";
let D=null,sel=null,viewMode='list';

function getTheme(){return document.documentElement.getAttribute("data-theme")||"light"}
function setTheme(t){document.documentElement.setAttribute("data-theme",t);localStorage.setItem(THEME_KEY,t);document.getElementById("themeToggle").textContent=t==="light"?"\u263E":"\u263C"}
function toggleTheme(){setTheme(getTheme()==="light"?"dark":"light")}
document.addEventListener("DOMContentLoaded",function(){document.getElementById("themeToggle").textContent=getTheme()==="light"?"\u263E":"\u263C"});

function isSubscribed(){return localStorage.getItem(SUBSCRIPTION_KEY)==="true"}
function setSubscribed(v){localStorage.setItem(SUBSCRIPTION_KEY,v?"true":"false");updateSubscriptionUI()}
function updateSubscriptionUI(){
  if(!SUBSCRIPTION_ENABLED){document.getElementById("adBanner").style.display="block";document.getElementById("adSidebar").style.display="block";return}
  const sub=isSubscribed();
  document.getElementById("adBanner").style.display=sub?"none":"block";
  document.getElementById("adSidebar").style.display=sub?"none":"block";
  document.getElementById("proBadge").style.display=sub?"inline":"none";
  document.getElementById("subscribeBtn").style.display=sub?"none":"inline-block";
}
function openSubscribeModal(){
  if(!SUBSCRIPTION_ENABLED)return;
  const m=document.getElementById("subscribeModal");if(m)m.classList.add("open");
  const c=document.getElementById("cancelOption");if(c)c.style.display=isSubscribed()?"block":"none";
}
function closeSubscribeModal(){document.getElementById("subscribeModal").classList.remove("open")}
function goToCheckout(plan){
  if(STRIPE_CHECKOUT_URL&&STRIPE_CHECKOUT_URL!=="#"){
    window.location.href=STRIPE_CHECKOUT_URL+(STRIPE_CHECKOUT_URL.includes("?")?"&":"?")+"plan="+plan;
  }else{
    setSubscribed(true);closeSubscribeModal();
  }
}
document.addEventListener("DOMContentLoaded",updateSubscriptionUI);
function esc(t){const d=document.createElement("div");d.textContent=t;return d.innerHTML}
function scoreColor(s){if(s>=0.65)return"var(--green)";if(s>=0.5)return"var(--amber)";return"var(--red)"}
function badgeClass(label){const l=(label||"").toLowerCase();if(l.includes("high")||l.includes("very"))return"badge-high";if(l.includes("medium"))return"badge-medium";if(l.includes("low"))return"badge-low";return"badge-weak"}
function confidenceText(label,pct){const l=(label||"").toLowerCase();if(l.includes("very")||l.includes("high"))return"Strong confidence. Signals align well.";if(l.includes("medium"))return"Moderate confidence. Worth watching.";if(l.includes("low"))return"Lower confidence. Proceed with caution.";return"Lower confidence. Not all signals align."}
function ideaAction(i){if((i.side||"").toUpperCase()==="LONG")return{action:"Buy",how:""};return{action:"Bet against",how:`Sell if you hold ${i.symbol}; otherwise avoid buying. Shorting (betting against) isn't available in most retail apps.`}}
function pct(v){return v!=null?Math.round(v*100)+"%":"N/A"}
function fmtCap(v){if(!v)return"N/A";if(v>=1e12)return"$"+(v/1e12).toFixed(1)+"T";if(v>=1e9)return"$"+(v/1e9).toFixed(1)+"B";if(v>=1e6)return"$"+(v/1e6).toFixed(0)+"M";return"$"+v}
function riskText(r){if(r==="low")return"Lower risk. Stronger signal confirmation.";if(r==="medium")return"Moderate risk. Some confirmation gaps.";return"Higher risk. Limited market confirmation."}
function rewardLabel(score){if(score>=0.65)return"Strong";if(score>=0.5)return"Moderate";return"Weak"}
function riskReward(signal){const r=signal?.risk_level||"medium";const score=signal?.score?.final_score??0;const rew=rewardLabel(score);return`Risk: ${r.charAt(0).toUpperCase()+r.slice(1)} · Reward: ${rew}`}
function eventLabel(t){const m={"oil_supply_shock":"Oil Supply Shock","government_stimulus":"Government Stimulus","rate_hike":"Interest Rate Move","shipping_disruption":"Shipping Disruption","sanctions":"Sanctions / Geopolitics","natural_disaster":"Natural Disaster","other":"Macro Event"};return m[t]||t}
function sourcesFallback(s,sc){
  const pub=s.event?.source_publication||"news outlets";
  const src=s.source_count||1;
  const etf=sc?.sector_etf?" We used "+sc.sector_etf+" as the sector proxy.":"";
  return "We looked at the article from "+pub+" ("+src+" source"+(src!==1?"s":"")+" in total). We also checked sector and stock price action."+etf;
}
function reasoningFallback(s,sc,sectorName){
  const eff=s.event?.expected_effect||"sector-specific news may affect related equities";
  const sector=sectorName||"this sector";
  return "The headline suggests "+eff.toLowerCase()+". For "+sector+", similar macro events have historically tended to move related names. We think this is worth watching given the current market context.";
}
function scoreBreakdownText(et,sector,cluster,sc,srcCount){
  const ev=(et||"other").toLowerCase();
  const src=srcCount||1;
  const newsDesc={
    oil_supply_shock:"For energy supply shocks, we evaluate how clearly the article describes supply disruption (production cuts, outages, geopolitical risk), price impact on oil/gas, and affected regions. We factor in source credibility and how many outlets report it ("+src+" source"+(src!==1?"s":"")+"). Multiple confirmations strengthen the signal.",
    government_stimulus:"For policy and stimulus events, we assess how clearly the article describes fiscal measures, infrastructure spending, or sector-specific support. We weigh source credibility, timing, and whether the news directly supports this sector's thesis. "+src+" source"+(src!==1?"s":"")+" reporting adds confidence.",
    rate_hike:"For rate and monetary policy events, we evaluate how explicitly the article describes Fed/ECB actions, inflation outlook, or yield implications. We factor in source credibility and whether the narrative aligns with financials (bullish) vs rate-sensitive sectors (bearish). "+src+" source"+(src!==1?"s":"")+" reporting adds weight.",
    shipping_disruption:"For logistics and supply chain events, we assess how clearly the article describes disruptions (ports, routes, capacity), cost impact, and affected industries. We weigh source credibility and how many outlets confirm the disruption ("+src+" source"+(src!==1?"s":"")+").",
    sanctions:"For sanctions and geopolitics, we evaluate how clearly the article describes trade restrictions, export controls, or affected sectors. We factor in source credibility and whether the narrative aligns with this sector's exposure. "+src+" source"+(src!==1?"s":"")+" reporting strengthens the signal.",
    natural_disaster:"For disaster and weather events, we assess how clearly the article describes crop damage, supply impact, or infrastructure disruption. We weigh source credibility and recency. These events are often time-sensitive. "+src+" source"+(src!==1?"s":"")+" reporting adds confidence.",
    other:"We evaluate how confident the event analysis is, how trustworthy the source is, how many sources report it ("+src+" source"+(src!==1?"s":"")+"), how recent the news is, and how well it matches this sector."
  };
  const etfHint=sc?.sector_etf?` We used ${sc.sector_etf} as the sector proxy.`:"";
  const marketDesc={
    oil_supply_shock:"We compared energy sector ETFs (XLE, OIH) and key oil/gas stocks to the broader market. Rising energy prices and sector outperformance support this supply-shock thesis. We also checked trading volume and how many of the key stocks are moving in the expected direction."+etfHint,
    government_stimulus:"We compared construction, materials, and infrastructure-related ETFs to the broader market. If they're outperforming on stimulus news, that supports the thesis. We also checked volume and breadth across the recommended stocks."+etfHint,
    rate_hike:"We compared financials and rate-sensitive sectors to the broader market. Banks typically benefit from higher rates; REITs and utilities often underperform. We checked volume and how many of the key stocks agree with the direction."+etfHint,
    shipping_disruption:"We compared shipping and logistics stocks to the broader market. If freight rates and shipping names are moving higher on disruption news, that supports the thesis. We also checked volume and breadth across the recommended names."+etfHint,
    sanctions:"We compared affected sectors (e.g. semiconductors, defense, commodities) to the broader market. Sanctions and export controls often create sector-specific winners and losers. We checked volume and price alignment."+etfHint,
    natural_disaster:"We compared agriculture, fertilizers, and insurance sectors to the broader market. Crop damage and supply disruption typically move these sectors. We checked volume and how many of the key stocks agree."+etfHint,
    other:"We compared this sector's ETFs and stocks to the broader market. If they're moving in the right direction, that supports the idea. We also checked trading volume and how many of the key stocks agree."+etfHint
  };
  const histDesc={
    oil_supply_shock:"Historical oil supply shocks have shown energy stocks tend to outperform while airlines and refiners underperform. We factor in typical win rates, average returns, and drawdowns for this event type from past data.",
    government_stimulus:"Historical stimulus events have shown construction and materials sectors often outperform in the months following. We factor in typical win rates and average returns for similar policy-driven setups.",
    rate_hike:"Historical rate-hike cycles have shown financials typically outperform while REITs and growth stocks underperform. We factor in typical win rates and drawdowns for this event type.",
    shipping_disruption:"Historical shipping disruptions (Suez, Red Sea, etc.) have shown freight and shipping stocks often outperform while import-dependent sectors lag. We factor in typical win rates and drawdowns.",
    sanctions:"Historical sanction events have shown mixed outcomes by sector. We factor in typical win rates and drawdowns for affected industries.",
    natural_disaster:"Historical disaster events have shown agriculture and fertilizer sectors often outperform. We factor in typical win rates and drawdowns for this event type.",
    other:"We looked at how similar past events of this type have played out: win rate, average returns, and typical drawdowns from historical data."
  };
  return{news:newsDesc[ev]||newsDesc.other,market:marketDesc[ev]||marketDesc.other,hist:histDesc[ev]||histDesc.other};
}

async function loadDaily(){
  try{
    const r=await fetch("/api/v1/daily");
    if(!r.ok)return;
    const d=await r.json();
    if(d&&d.sector_groups&&d.sector_groups.length>0){
      D=d;sel=null;
      const t=new Date(d.generated_at).toLocaleTimeString();
      document.getElementById("scanStatus").textContent=`Daily scan: ${d.sector_groups.length} sectors with signals (${t}) — Run a custom scan below`;
      renderList();
    }
  }catch(e){}
}
loadDaily();

let _currentEventSource=null;
function runScan(cancelOnly){
  const btn=document.getElementById("scanBtn"),st=document.getElementById("scanStatus"),wl=document.getElementById("watchlist").value.trim();
  if(_currentEventSource){
    _currentEventSource.close();_currentEventSource=null;
    btn.disabled=false;btn.textContent="Scan Markets";
    st.textContent="Scan cancelled.";
    document.getElementById("sectorList").innerHTML=D&&D.sector_groups&&D.sector_groups.length?'':`<div class="empty-state"><p>Scan cancelled. Enter a topic above or run a broad scan to try again.</p></div>`;
    if(D&&D.sector_groups&&D.sector_groups.length)renderList();
    if(cancelOnly)return;
  }
  btn.disabled=false;btn.textContent="Cancel";
  st.innerHTML='<span class="spinner"></span>Initializing scan...';
  document.getElementById("sectorList").innerHTML='<div class="empty-state"><div class="spinner" style="width:24px;height:24px;border-width:3px"></div><p id="progressText" style="margin-top:1rem">Connecting to server...</p></div>';

  const url=wl?"/api/v1/scan/stream?watchlist="+encodeURIComponent(wl):"/api/v1/scan/stream";
  const es=new EventSource(url);_currentEventSource=es;
  const pt=()=>document.getElementById("progressText");
  function done(){es.close();_currentEventSource=null;btn.disabled=false;btn.textContent="Scan Markets";}

  es.addEventListener("progress",function(e){
    if(_currentEventSource!==es)return;
    const msg=JSON.parse(e.data).message;
    st.innerHTML='<span class="spinner"></span>'+esc(msg);
    if(pt())pt().textContent=msg;
  });

  es.addEventListener("result",function(e){
    if(_currentEventSource!==es)return;
    done();
    const d=JSON.parse(e.data);D=d;sel=null;
    const t=new Date(d.generated_at).toLocaleTimeString();
    st.textContent=`Scanned ${d.sectors_scanned.length} sectors — ${d.sector_groups.length} produced actionable signals (${t})`;
    renderList();
  });

  es.addEventListener("error",function(e){
    if(_currentEventSource!==es)return;
    done();
    st.textContent="Scan failed. Check server logs.";
    document.getElementById("sectorList").innerHTML='<div class="empty-state"><p>Something went wrong. Try again or check your API keys.</p></div>';
  });
}

function setViewMode(m){viewMode=m;document.getElementById('btnList').classList.toggle('active',m==='list');document.getElementById('btnTagCloud').classList.toggle('active',m==='tagcloud');renderList()}
function toggleSector(key){
  sel=(sel===key)?null:key;
  renderList();
}

function renderTagCloud(){
  const el=document.getElementById("sectorList");el.innerHTML="";
  if(!D||!D.sector_groups.length){el.innerHTML='<div class="empty-state" style="padding:2rem"><p>No sectors had actionable signals this run. Try a broader topic or run a full scan to explore more sectors.</p></div>';return}
  const scores=D.sector_groups.map(g=>g.event_clusters[0]?.top_signal?.score?.final_score??0);
  const minS=Math.min(...scores),maxS=Math.max(...scores),range=Math.max(maxS-minS,.01);
  const cloud=document.createElement("div");cloud.className="tag-cloud";
  D.sector_groups.forEach(g=>{
    const score=g.event_clusters[0]?.top_signal?.score?.final_score??0;
    const size=0.9+(score-minS)/range*1.1;
    const sizePx=Math.round(14+size*10);
    const isOpen=g.sector_key===sel;
    const tag=document.createElement("span");
    tag.className="tag-cloud-tag"+(isOpen?" active":"");
    tag.style.fontSize=sizePx+"px";
    tag.style.color=scoreColor(score);
    tag.style.background=score>=0.65?"rgba(16,185,129,.15)":score>=0.5?"rgba(245,158,11,.15)":"rgba(239,68,68,.1)";
    tag.style.borderColor=score>=0.65?"rgba(16,185,129,.4)":score>=0.5?"rgba(245,158,11,.35)":"rgba(239,68,68,.25)";
    tag.textContent=g.sector_display_name;
    tag.onclick=()=>toggleSector(g.sector_key);
    cloud.appendChild(tag);
  });
  el.appendChild(cloud);
  const hint=document.createElement("div");hint.className="tag-cloud-hint";hint.textContent="Larger = stronger signal · Click to expand";el.appendChild(hint);
  if(sel){
    const detail=document.createElement("div");detail.className="sector-detail-inline";detail.style.marginTop="1.5rem";
    const g=D.sector_groups.find(x=>x.sector_key===sel);if(g)detail.innerHTML=renderDetailHTML(g);
    el.appendChild(detail);
  }
}

function renderList(){
  const el=document.getElementById("sectorList");el.innerHTML="";
  const toggle=document.getElementById("viewToggle");
  if(!D||!D.sector_groups.length){if(toggle)toggle.style.display="none";el.innerHTML='<div class="empty-state" style="padding:2rem"><p>No sectors had actionable signals this run. Try a broader topic or run a full scan to explore more sectors.</p></div>';return}
  if(toggle){toggle.style.display="flex";document.getElementById("btnList").classList.toggle("active",viewMode==="list");document.getElementById("btnTagCloud").classList.toggle("active",viewMode==="tagcloud")}
  if(viewMode==="tagcloud"){renderTagCloud();return}
  D.sector_groups.forEach(g=>{
    const isOpen=g.sector_key===sel;
    const top=g.event_clusters[0]?.top_signal?.score;
    const score=top?.final_score??0;
    const label=top?.label??"N/A";
    const item=document.createElement("div");
    item.className="sector-item";
    const c=document.createElement("div");
    c.className="sector-card"+(isOpen?" active":"");
    c.onclick=()=>toggleSector(g.sector_key);
    c.innerHTML=`
      <span class="chevron">&#x25BC;</span>
      <h3>${esc(g.sector_display_name)}</h3>
      <div class="meta">
        <span>${g.category}</span>
        <span>${g.source_count} source${g.source_count!==1?"s":""}</span>
        <span>${g.event_clusters.length} event${g.event_clusters.length!==1?"s":""}</span>
      </div>
      <div class="score-bar"><div class="score-bar-fill" style="width:${score*100}%;background:${scoreColor(score)}"></div></div>
      <div class="score-row"><span class="score-label">Confidence</span><span class="badge ${badgeClass(label)}">${label}</span></div>
      <div class="risk-reward-row"><span class="risk-pill risk-${(g.event_clusters[0]?.top_signal?.risk_level)||"medium"}">${riskReward(g.event_clusters[0]?.top_signal)}</span></div>
    `;
    item.appendChild(c);
    if(isOpen){
      const detail=document.createElement("div");
      detail.className="sector-detail-inline";
      detail.innerHTML=renderDetailHTML(g);
      item.appendChild(detail);
    }
    el.appendChild(item);
  });
}

function renderDetailHTML(g){
  const grouped={};
  g.top_trade_ideas.forEach(i=>{
    const a=ideaAction(i);
    const key=(a.action+"|"+i.rationale);
    if(!grouped[key])grouped[key]={action:a.action,rationale:i.rationale,symbols:[]};
    grouped[key].symbols.push(i.symbol);
  });
  const topSig=g.event_clusters[0]?.top_signal;
  const ev=topSig?.event;
  const sc=topSig?.score;
  const horizon=ev?.horizon?"Typical hold: "+ev.horizon:"";
  const de=sc?.days_to_earnings;
  const earnings=de!=null?"Earnings in "+de+" day"+(de===1?"":"s"):"";
  const breadth=sc?.breadth_confirmation;
  const mktConfirm=breadth!=null?(breadth>=0.5?"Market confirming":breadth<0.4?"Market not yet confirming":""):"";
  const eventType=g.event_clusters[0]?.cluster_label||(ev?.event_type?eventLabel(ev.event_type):"");
  const insightParts=[horizon,earnings,mktConfirm,eventType].filter(Boolean);
  const insightHtml=insightParts.length?`<div class="idea-insights">${insightParts.map(p=>esc(p)).join(" · ")}</div>`:"";
  const ideas=Object.values(grouped).map(gr=>{
    const syms=gr.symbols.slice(0,12);
    const more=gr.symbols.length>12?" +"+(gr.symbols.length-12)+" more":"";
    const symBoxes=syms.map(s=>`<span class="symbol-box">${esc(s)}</span>`).join("");
    const how=gr.action==="Bet against"?"Sell if you hold any of these; otherwise avoid buying. Shorting (betting against) isn't available in most retail apps.":"";
    const chipClass=gr.action==="Buy"?"buy":"avoid";
    return`
    <div class="idea-chip ${chipClass}">
      <div class="idea-action-row">
        <span class="action-badge ${chipClass}">${gr.action}</span>
        <div class="symbols-row">${symBoxes}${more?`<span class="symbol-more">${esc(more)}</span>`:""}</div>
      </div>
      ${how?`<div class="idea-how">${esc(how)}</div>`:""}
      <div class="rationale">${esc(gr.rationale)}</div>
      ${insightHtml}
    </div>`;
  }).join("");
  const clusters=g.event_clusters.map((cl,ci)=>{
    const sigs=cl.signals.map((s,si)=>{
      const sc=s.score;
      const titleHtml=s.event.source_url
        ?`<a href="${s.event.source_url}" target="_blank" rel="noopener" onclick="event.stopPropagation()">${esc(s.event.source_title)}</a>`
        :esc(s.event.source_title);
      const pub=s.event.source_publication?`<div class="signal-source">${esc(s.event.source_publication)}</div>`:"";
      const notes=sc?.notes?.length?`<div class="notes-box"><strong>Heads up:</strong> ${sc.notes.map(esc).join("; ")}</div>`:"";
      const nv=sc?.news_score??0;const mv=sc?.market_score??0;const hv=sc?.historical_score??0;const fv=sc?.final_score??0;
      const hwId='hw-'+ci+'-'+si;
      const sourcesStr=sc?.sources_explanation||sourcesFallback(s,sc);
      const reasoningStr=sc?.reasoning_explanation||reasoningFallback(s,sc,g.sector_display_name);
      const homeworkHtml=sc?`
        <div class="homework-detail" id="${hwId}">
          <h5>${esc(g.sector_display_name||"")} (${eventLabel(s.event?.event_type)})</h5>
          <div class="score-graph">
            <div class="score-graph-bar"><div class="bar" style="height:${nv*100}%;background:${scoreColor(nv)}"></div><span class="lbl">News</span></div>
            <div class="score-graph-bar"><div class="bar" style="height:${mv*100}%;background:${scoreColor(mv)}"></div><span class="lbl">Market</span></div>
            <div class="score-graph-bar"><div class="bar" style="height:${hv*100}%;background:${scoreColor(hv)}"></div><span class="lbl">History</span></div>
            <div class="score-graph-bar"><div class="bar" style="height:${fv*100}%;background:${scoreColor(fv)}"></div><span class="lbl">Overall</span></div>
          </div>
          <div class="homework-section">
            <h5>Sources we analyzed</h5>
            <p>${esc(sourcesStr)}</p>
          </div>
          <div class="homework-section">
            <h5>Why we think this</h5>
            <p>${esc(reasoningStr)}</p>
          </div>
        </div>`:"";
      return`
        <div class="signal-card">
          <h4>${titleHtml}</h4>
          ${pub}
          <div class="signal-summary">${esc(s.event.expected_effect)}</div>
          <div class="score-explainer">
            <div class="score-factor">
              <div class="factor-bar-wrap"><span class="factor-bar" style="width:${nv*100}%;background:${scoreColor(nv)}"></span></div>
              <span class="factor-label">News relevance</span>
              <span class="factor-desc">How well the story supports this idea</span>
            </div>
            <div class="score-factor">
              <div class="factor-bar-wrap"><span class="factor-bar" style="width:${mv*100}%;background:${scoreColor(mv)}"></span></div>
              <span class="factor-label">Market check</span>
              <span class="factor-desc">Does current price action agree?</span>
            </div>
            <div class="score-factor">
              <div class="factor-bar-wrap"><span class="factor-bar" style="width:${hv*100}%;background:${scoreColor(hv)}"></span></div>
              <span class="factor-label">Track record</span>
              <span class="factor-desc">How similar setups have performed</span>
            </div>
          </div>
          <div class="score-bar"><div class="score-bar-fill" style="width:${fv*100}%;background:${scoreColor(fv)}"></div></div>
          <div class="confidence-row">
            <span class="confidence-text">${confidenceText(sc?.label,pct(fv))}</span>
            <span class="badge ${badgeClass(sc?.label)}">${sc?.label??"N/A"}</span>
            <span class="risk-pill risk-${s.risk_level||"medium"}" ${sc?`onclick="event.stopPropagation();document.getElementById('${hwId}').classList.toggle('open')" title="View detailed score breakdown"`:""}>${riskReward(s)}</span>
          </div>
          ${sc?`<span class="homework-toggle" onclick="event.stopPropagation();document.getElementById('${hwId}').classList.toggle('open')">View detailed score breakdown</span>`:""}
          ${homeworkHtml}
          ${notes}
        </div>`;
    }).join("");
    return`
      <div class="cluster-section">
        <div class="cluster-header">
          <h3>${esc(cl.cluster_label)}</h3>
          <span class="count">${cl.signal_count} signal${cl.signal_count!==1?"s":""} · ${cl.source_count} source${cl.source_count!==1?"s":""}</span>
        </div>
        ${sigs}
      </div>`;
  }).join("");

  const ideasNote=g.category==="custom"&&(!g.top_trade_ideas||!g.top_trade_ideas.length)?`<div class="ideas-note">No specific symbols for this topic. Results show news and macro signals only.</div>`:"";
  return`
    <div class="detail-header">
      ${ideas?`<div><div class="sidebar-label">Trade ideas</div><div class="ideas-grid">${ideas}</div></div>`:ideasNote}
    </div>
    ${clusters}`;
}
</script>
</body>
</html>
"""
