from __future__ import annotations

import asyncio
import json
import logging
import re
from collections import defaultdict
from typing import Callable, Awaitable

from app.config import current_time_context, settings
from app.event_detector import EventDetector

logger = logging.getLogger("plutus.scan")

ProgressCallback = Callable[[str], Awaitable[None]]

async def _noop_progress(msg: str) -> None:
    pass
from app.keywords import (
    KeywordGenerator,
    extract_filter_keywords,
    is_relevant_to_keywords,
    matched_keywords,
)
from app.market import BENCHMARK_SYMBOL, MarketDataProvider, MarketInsightProvider, sector_etf_for
from app.models import EventCluster, EventType, GroupedRunResponse, SectorGroup, SectorImpact, TradeIdea
from app.news import NewsProvider
from app.reasoning import infer_impacts
from app.scoring import score_signal
from app.sectors import get_sector, resolve_sector_keys
from app.suggestions import build_signal
from app.symbol_discovery import (
    build_trade_ideas_from_discovery,
    discover_symbols_and_rationale,
)


EVENT_CLUSTER_LABELS: dict[EventType, str] = {
    EventType.OIL_SUPPLY_SHOCK: "Supply Shock",
    EventType.GOVERNMENT_STIMULUS: "Policy Support",
    EventType.RATE_HIKE: "Rates",
    EventType.SHIPPING_DISRUPTION: "Logistics Disruption",
    EventType.SANCTIONS: "Geopolitics",
    EventType.NATURAL_DISASTER: "Disaster Impact",
    EventType.OTHER: "General Macro",
}


def _risk_from_score(score: float) -> str:
    if score >= 0.75:
        return "low"
    if score >= 0.55:
        return "medium"
    return "high"


async def _discover_custom_symbols(
    keyword_generator: KeywordGenerator,
    topic: str,
    query: str,
    sample_titles: list[str],
) -> list[str]:
    """Use AI to discover tradable ticker symbols for custom user topics."""
    if keyword_generator.client is None:
        return []
    prompt = f"""Return 4-8 liquid tradable ticker symbols for this market topic.
Prefer major US-listed names and ETFs when relevant.
Return JSON only: {{"symbols":["SYM1","SYM2"]}}

Current date and time: {current_time_context()}

Topic: {topic}
News query: {query}
Sample headlines:
{chr(10).join(f"- {t}" for t in sample_titles[:6])}
"""
    try:
        response = await keyword_generator.client.responses.create(
            model=keyword_generator.model,
            input=prompt,
            temperature=0.0,
        )
        text = (response.output_text or "").strip()
        symbols: list[str] = []
        try:
            parsed = json.loads(text)
            items = parsed.get("symbols", []) if isinstance(parsed, dict) else parsed
            if isinstance(items, list):
                symbols = [str(x).upper().strip() for x in items if isinstance(x, str)]
        except Exception:
            # Fallback: pull ticker-like tokens from model text.
            symbols = re.findall(r"\b[A-Z][A-Z0-9.-]{0,5}\b", text.upper())
        cleaned: list[str] = []
        seen: set[str] = set()
        for sym in symbols:
            if sym in seen:
                continue
            if sym in {"AI", "OR", "AND", "USD", "NEWS"}:
                continue
            seen.add(sym)
            cleaned.append(sym)
            if len(cleaned) >= 8:
                break
        return cleaned
    except Exception as e:
        logger.debug("Custom symbol discovery failed for %s: %s", topic, e)
        return []


async def _scan_one_sector(
    sector_key: str,
    provider: NewsProvider,
    detector: EventDetector,
    keyword_generator: KeywordGenerator,
    market_provider: MarketDataProvider,
    insight_provider: MarketInsightProvider,
    max_articles_per_sector: int,
    on_progress: ProgressCallback = _noop_progress,
) -> SectorGroup | None:
    sector = get_sector(sector_key)
    if not sector:
        logger.warning("Sector %s not found, skipping", sector_key)
        return None
    # For custom user topics, let AI expand the query dynamically.
    if sector.category == "custom":
        await on_progress(f"Researching {sector.display_name} with AI")
        query = await keyword_generator.generate_for_sector(sector)
    else:
        query = keyword_generator.static_query(sector)
    logger.debug("Sector %s: query=%r", sector_key, query[:80] + "..." if len(query) > 80 else query)
    articles = await provider.fetch(query, max_articles_per_sector)
    logger.info("Sector %s: fetched %d articles", sector_key, len(articles))
    await on_progress(f"Fetched {len(articles)} articles — filtering for {sector.display_name}")
    filter_keywords = extract_filter_keywords(query)

    sector_signals = []
    sector_matched_keywords: set[str] = set()
    source_keys: set[str] = set()

    # Block non-financial sources (PyPI, GitHub, etc.)
    _NON_NEWS_SOURCES = ("pypi.org", "github.com", "npmjs.com", "crates.io")
    def _is_news_source(article) -> bool:
        src = (article.source or "").lower()
        url = (article.url or "").lower()
        return not any(block in src or block in url for block in _NON_NEWS_SOURCES)

    relevant_articles = []
    for article in articles:
        if not _is_news_source(article):
            continue
        if filter_keywords and not is_relevant_to_keywords(article.title, article.description, filter_keywords):
            continue
        relevant_articles.append(article)
    if len(relevant_articles) < len(articles):
        logger.debug("Sector %s: %d/%d articles passed keyword filter", sector_key, len(relevant_articles), len(articles))
    # For custom sectors, don't fall back to random articles when nothing matches
    if not relevant_articles and articles and sector.category != "custom":
        logger.info("Sector %s: all %d articles filtered out, using top %d by title match", sector_key, len(articles), min(2, len(articles)))
        relevant_articles = [a for a in articles[:2] if _is_news_source(a)]

    custom_symbols: list[str] = []
    if sector.category == "custom":
        title_samples = [a.title for a in (relevant_articles or articles) if a.title]
        custom_symbols = await _discover_custom_symbols(keyword_generator, sector.display_name, query, title_samples)

    # First pass: detect events (fast heuristic) and collect work items
    await on_progress(f"Detecting events in {len(relevant_articles)} articles for {sector.display_name}")
    work_items: list[tuple] = []
    for article in relevant_articles:
        article_hits = matched_keywords(article.title, article.description, filter_keywords)
        article = article.model_copy(update={"sector_key": sector.key, "query_used": query})
        event = await detector.detect(article)
        if not event:
            continue
        impacts = infer_impacts(event)
        if sector.key not in {impact.sector for impact in impacts}:
            impacts = [
                SectorImpact(
                    sector=sector.key,
                    direction="bullish",
                    rationale=f"{sector.display_name} news flow may create tradable sector dispersion.",
                ),
                *impacts,
            ]
        if sector.category == "custom":
            impacts = [i for i in impacts if i.sector == sector.key]
        if not impacts:
            continue
        work_items.append((article, event, impacts, article_hits))

    # Market data pre-warmed globally before sector processing; cache hits here

    # Process articles in parallel (symbol discovery + scoring)
    sem = asyncio.Semaphore(settings.scan_concurrency)
    signals_done: list[int] = [0]

    async def process_one(idx: int, item: tuple) -> tuple | None:
        article, event, impacts, article_hits = item
        async with sem:
            title_snippet = (article.title or "")[:45] + ("..." if len(article.title or "") > 45 else "")
            await on_progress(f"{sector.display_name}: Analyzing — {title_snippet}")
            trade_ideas = None
            if keyword_generator.client and idx < settings.symbol_discovery_limit:
                try:
                    discovered = await discover_symbols_and_rationale(
                        event, impacts, keyword_generator.client, settings.openai_model
                    )
                    if discovered:
                        trade_ideas = build_trade_ideas_from_discovery(discovered)
                except Exception as e:
                    logger.debug("Symbol discovery failed, using fallback: %s", e)

            base_signal = build_signal(event, impacts)
            if trade_ideas:
                base_signal = base_signal.model_copy(update={"trade_ideas": trade_ideas})

            signal = base_signal.model_copy(
                update={
                    "published_at": article.published_at,
                    "matched_keywords": article_hits,
                    "sector_key": sector.key,
                    "sector_display_name": sector.display_name,
                    "source_count": 1,
                }
            )
            if sector.category == "custom" and not signal.trade_ideas and custom_symbols:
                lead = impacts[0] if impacts else SectorImpact(
                    sector=sector.key,
                    direction="bullish",
                    rationale=f"{sector.display_name} news flow may drive near-term price moves.",
                )
                side = "LONG" if lead.direction == "bullish" else "SHORT"
                dynamic_ideas = [
                    TradeIdea(side=side, symbol=sym, sector=sector.key, rationale=lead.rationale)
                    for sym in custom_symbols
                ]
                signal = signal.model_copy(update={"trade_ideas": dynamic_ideas})

            await on_progress(f"{sector.display_name}: Scoring signal...")
            score = await score_signal(
                signal,
                market_provider,
                insight_provider,
                openai_client=keyword_generator.client,
                openai_model=settings.openai_model,
                skip_explanations=settings.skip_score_explanations,
                include_insight=settings.include_insight,
                include_stock_market_data=settings.include_stock_market_data,
            )
            scored = signal.model_copy(update={"score": score, "risk_level": _risk_from_score(score.final_score)})
            signals_done[0] += 1
            await on_progress(f"{sector.display_name}: Scored {signals_done[0]}/{len(work_items)} signals")
            return (scored, article_hits, article.url or article.title)

    if work_items:
        await on_progress(f"Analyzing {len(work_items)} signals for {sector.display_name}")
    results = await asyncio.gather(*[process_one(idx, item) for idx, item in enumerate(work_items)])
    for r in results:
        if r is not None:
            scored_sig, hits, src = r
            sector_signals.append(scored_sig)
            sector_matched_keywords.update(hits)
            source_keys.add(src)

    if not sector_signals:
        logger.debug("Sector %s: no signals produced", sector_key)
        return None

    logger.info("Sector %s: %d signals, %d event clusters", sector_key, len(sector_signals), len(set(s.event.event_type for s in sector_signals)))
    clusters_by_type = defaultdict(list)
    for signal in sector_signals:
        clusters_by_type[signal.event.event_type].append(signal)

    event_clusters: list[EventCluster] = []
    for event_type, signals in clusters_by_type.items():
        cluster_sources = {signal.event.source_url or signal.event.source_title for signal in signals}
        top_signal = max(signals, key=lambda item: item.score.final_score if item.score else item.event.confidence)
        event_clusters.append(
            EventCluster(
                cluster_label=EVENT_CLUSTER_LABELS[event_type],
                event_type=event_type,
                signal_count=len(signals),
                source_count=len(cluster_sources),
                top_signal=top_signal,
                signals=sorted(
                    signals,
                    key=lambda item: item.score.final_score if item.score else item.event.confidence,
                    reverse=True,
                ),
            )
        )

    event_clusters.sort(
        key=lambda item: (
            item.top_signal.score.final_score if item.top_signal.score else item.top_signal.event.confidence,
            item.signal_count,
        ),
        reverse=True,
    )
    top_trade_ideas = []
    seen_symbols: set[str] = set()
    for cluster in event_clusters:
        for signal in cluster.signals[:3]:  # Pull from top 3 signals per cluster
            for idea in signal.trade_ideas:
                if idea.symbol not in seen_symbols:
                    seen_symbols.add(idea.symbol)
                    top_trade_ideas.append(idea)
                if len(top_trade_ideas) >= 16:
                    break
            if len(top_trade_ideas) >= 16:
                break
        if len(top_trade_ideas) >= 16:
            break

    return SectorGroup(
        sector_key=sector.key,
        sector_display_name=sector.display_name,
        category=sector.category,
        matched_keywords=sorted(sector_matched_keywords),
        source_count=len(source_keys),
        strongest_cluster=event_clusters[0].cluster_label if event_clusters else None,
        top_trade_ideas=top_trade_ideas,
        event_clusters=event_clusters,
    )


async def run_sector_scan(
    watchlist: list[str],
    max_articles_per_sector: int,
    max_sectors: int,
    provider: NewsProvider,
    detector: EventDetector,
    keyword_generator: KeywordGenerator,
    market_provider: MarketDataProvider,
    insight_provider: MarketInsightProvider,
    on_progress: ProgressCallback = _noop_progress,
) -> GroupedRunResponse:
    sector_keys = resolve_sector_keys(watchlist)[:max_sectors]
    logger.info("Scanning %d sectors: %s", len(sector_keys), sector_keys)

    await on_progress(f"Fetching news for {len(sector_keys)} sectors...")

    # News warmup and market pre-warm in parallel
    from app.news import PooledNewsProvider

    async def warm_news() -> None:
        if isinstance(provider, PooledNewsProvider):
            await provider.fetch("warmup", 0)

    async def warm_market() -> None:
        etf_symbols = [sector_etf_for(sk) for sk in sector_keys]
        await asyncio.gather(
            market_provider.snapshot(BENCHMARK_SYMBOL),
            *[market_provider.snapshot(etf) for etf in etf_symbols],
        )

    if settings.fast_scan:
        await warm_news()
    else:
        await on_progress("Loading news and market data...")
        await asyncio.gather(warm_news(), warm_market())
    await on_progress(f"News pool ready — starting sector analysis")

    done_count = 0
    total = len(sector_keys)

    async def sector_progress(msg: str) -> None:
        await on_progress(msg)

    async def run_one(sector_key: str) -> SectorGroup | None:
        nonlocal done_count
        s = get_sector(sector_key)
        name = s.display_name if s else sector_key.replace("_", " ").title()
        await on_progress(f"Starting {name}...")
        result = await _scan_one_sector(
            sector_key, provider, detector, keyword_generator,
            market_provider, insight_provider, max_articles_per_sector,
            on_progress=sector_progress,
        )
        done_count += 1
        await on_progress(f"Completed {name} ({done_count}/{total})")
        return result

    results = await asyncio.gather(*[run_one(sk) for sk in sector_keys])
    sector_groups = [g for g in results if g is not None]
    logger.info("Scan: %d sectors yielded %d groups", len(sector_keys), len(sector_groups))
    await on_progress(f"Ranking {len(sector_groups)} sectors with signals")

    sector_groups.sort(
        key=lambda group: (
            max(
                (
                    cluster.top_signal.score.final_score if cluster.top_signal.score else cluster.top_signal.event.confidence
                    for cluster in group.event_clusters
                ),
                default=0.0,
            ),
            group.source_count,
        ),
        reverse=True,
    )

    from datetime import datetime, timezone

    return GroupedRunResponse(
        generated_at=datetime.now(timezone.utc),
        sectors_scanned=sector_keys,
        sector_groups=sector_groups,
    )
