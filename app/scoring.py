from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from app.config import current_time_context
from app.market import (
    BENCHMARK_SYMBOL,
    MarketDataProvider,
    MarketInsightProvider,
    representative_symbols,
    sector_etf_for,
)
from app.models import EventType, ScoreBreakdown, Signal

logger = logging.getLogger("plutus.scoring")
INSIGHT_TIMEOUT_SECONDS = 2.5

SOURCE_QUALITY_WEIGHTS: dict[str, float] = {
    "reuters": 1.0,
    "bloomberg": 0.98,
    "wall street journal": 0.95,
    "financial times": 0.9,
    "associated press": 0.88,
    "ap": 0.88,
    "cnbc": 0.82,
    "pbs": 0.72,
    "finnhub": 0.65,
    "mockwire": 0.6,
}

HISTORICAL_PRIORS: dict[EventType, tuple[float, float, float, float]] = {
    EventType.OIL_SUPPLY_SHOCK: (0.66, 0.7, 0.58, 0.75),
    EventType.GOVERNMENT_STIMULUS: (0.62, 0.64, 0.6, 0.68),
    EventType.RATE_HIKE: (0.58, 0.56, 0.62, 0.8),
    EventType.SHIPPING_DISRUPTION: (0.57, 0.52, 0.48, 0.45),
    EventType.SANCTIONS: (0.55, 0.5, 0.46, 0.42),
    EventType.NATURAL_DISASTER: (0.54, 0.45, 0.4, 0.38),
    EventType.OTHER: (0.5, 0.42, 0.46, 0.3),
}


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def confidence_label(score: float) -> str:
    if score >= 0.8:
        return "Very High"
    if score >= 0.65:
        return "High"
    if score >= 0.5:
        return "Medium"
    if score >= 0.35:
        return "Low"
    return "Lower confidence"


def _source_quality(source: str | None) -> float:
    if not source:
        return 0.6
    source_lower = source.lower()
    for name, weight in SOURCE_QUALITY_WEIGHTS.items():
        if name in source_lower:
            return weight
    return 0.65


def _source_count_score(source_count: int) -> float:
    if source_count >= 4:
        return 1.0
    if source_count == 3:
        return 0.75
    if source_count == 2:
        return 0.55
    return 0.35


def _recency_score(published_at: datetime | None) -> float:
    if published_at is None:
        return 0.5
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_hours = max((datetime.now(timezone.utc) - published_at).total_seconds() / 3600.0, 0.0)
    if age_hours < 2:
        return 1.0
    if age_hours < 8:
        return 0.8
    if age_hours < 24:
        return 0.6
    if age_hours < 72:
        return 0.35
    return 0.2


def _sector_relevance(signal: Signal) -> float:
    return clamp(len(signal.matched_keywords) / 3.0, 0.25, 1.0)


def compute_news_score(signal: Signal) -> float:
    event = signal.event
    return clamp(
        0.30 * event.confidence
        + 0.20 * _source_quality(event.source_publication)
        + 0.20 * _source_count_score(signal.source_count)
        + 0.15 * _recency_score(signal.published_at)
        + 0.15 * _sector_relevance(signal)
    )


def compute_historical_score(signal: Signal) -> float:
    hit_rate, avg_return_score, drawdown_score, sample_size_score = HISTORICAL_PRIORS[signal.event.event_type]
    return clamp(
        0.40 * hit_rate
        + 0.30 * avg_return_score
        + 0.20 * drawdown_score
        + 0.10 * sample_size_score
    )


async def compute_market_score(
    signal: Signal,
    market_provider: MarketDataProvider,
    *,
    include_stock_snapshots: bool = True,
) -> tuple[float, dict[str, float | None | str], list[str]]:
    notes: list[str] = []
    sector_key = signal.sector_key or (signal.trade_ideas[0].sector if signal.trade_ideas else "")
    etf_symbol = sector_etf_for(sector_key)
    picks = representative_symbols(signal.trade_ideas, limit=1) if include_stock_snapshots else []

    benchmark, sector_etf = await asyncio.gather(
        market_provider.snapshot(BENCHMARK_SYMBOL),
        market_provider.snapshot(etf_symbol),
    )

    if benchmark is None or sector_etf is None:
        notes.append("We couldn't get live market data to confirm this idea.")
        return 0.5, {
            "sector_etf": etf_symbol,
            "market_data_source": None,
            "sector_relative_strength": None,
            "stock_relative_strength": None,
            "volume_confirmation": None,
            "breadth_confirmation": None,
            "volatility_alignment": None,
        }, notes

    benchmark_day = benchmark.day_return or 0.0
    benchmark_five_day = benchmark.five_day_return or benchmark_day
    sector_day = sector_etf.day_return or 0.0
    sector_five_day = sector_etf.five_day_return or sector_day
    sector_relative_strength = clamp(((sector_day - benchmark_day) + (sector_five_day - benchmark_five_day) + 0.05) / 0.12)

    stock_scores: list[float] = []
    volume_scores: list[float] = []
    breadth_votes = 0
    total_votes = 0
    volatility_scores: list[float] = []

    if picks:
        snaps = await asyncio.gather(*[market_provider.snapshot(sym) for sym, _ in picks])
        for (symbol, side), snap in zip(picks, snaps):
            if snap is None:
                continue
            day_return = snap.day_return or 0.0
            relative = day_return - benchmark_day if side == "LONG" else benchmark_day - day_return
            stock_scores.append(clamp((relative + 0.05) / 0.10))
            if snap.volume_ratio is not None:
                volume_scores.append(clamp((snap.volume_ratio - 1.0) / 1.5))
            if snap.intraday_range_ratio is not None:
                volatility_scores.append(clamp(1.0 - max(snap.intraday_range_ratio - 0.02, 0.0) / 0.08))
            total_votes += 1
            if (side == "LONG" and day_return >= 0) or (side == "SHORT" and day_return <= 0):
                breadth_votes += 1

    stock_relative_strength = sum(stock_scores) / len(stock_scores) if stock_scores else 0.5
    volume_confirmation = sum(volume_scores) / len(volume_scores) if volume_scores else 0.5
    breadth_confirmation = breadth_votes / total_votes if total_votes else 0.5
    volatility_alignment = sum(volatility_scores) / len(volatility_scores) if volatility_scores else 0.5

    market_score = clamp(
        0.30 * sector_relative_strength
        + 0.25 * stock_relative_strength
        + 0.20 * volume_confirmation
        + 0.15 * breadth_confirmation
        + 0.10 * volatility_alignment
    )

    if include_stock_snapshots and total_votes == 0:
        notes.append("Market data isn't available for these stocks right now.")

    return market_score, {
        "sector_etf": etf_symbol,
        "market_data_source": sector_etf.provider_name or benchmark.provider_name,
        "sector_relative_strength": sector_relative_strength,
        "stock_relative_strength": stock_relative_strength,
        "volume_confirmation": volume_confirmation,
        "breadth_confirmation": breadth_confirmation,
        "volatility_alignment": volatility_alignment,
    }, notes


def _fmt(v: Any) -> str:
    if v is None:
        return "N/A"
    if isinstance(v, (int, float)):
        return f"{v:.0%}" if 0 <= v <= 1 else str(v)
    return str(v)


async def _generate_score_explanations(
    signal: Signal,
    news_score: float,
    market_score: float,
    historical_score: float,
    final_score: float,
    market_components: dict[str, Any],
    notes: list[str],
    openai_client: Any,
    model: str,
) -> tuple[str | None, str | None]:
    """Use LLM to generate sources + reasoning explanations."""
    event = signal.event
    event_type = getattr(event.event_type, "value", str(event.event_type))
    sector = signal.sector_display_name or (signal.trade_ideas[0].sector if signal.trade_ideas else "")
    source = event.source_publication or "unknown"
    src_count = signal.source_count or 1

    etf = market_components.get('sector_etf') or 'N/A'
    mkt_src = market_components.get('market_data_source') or 'market data'
    prompt = f"""You are helping an investor understand a macro trading signal. Generate 2 paragraphs. Do NOT use em dashes. Be specific to this event and sector. Do NOT explain scoring methodology. Focus on what we looked at and why this matters.

Current date and time: {current_time_context()}

1. SOURCES: In 2-3 sentences, describe what we analyzed. Include: the news article from {source} (headline: "{event.source_title[:80]}..."), {src_count} source(s) in total, sector proxy {etf}, and {mkt_src} for price action. Write naturally, like "We looked at..." or "Our analysis drew on...".

2. REASONING: In 2-4 sentences, explain why we think this signal matters. Reference the headline, what the news implies for {sector}, how similar {event_type} events have played out, and what the market data suggests. Write as if explaining your view to an investor, not describing a formula.

Event: {event_type}
Sector: {sector}
Headline: {event.source_title[:120]}
Expected effect: {event.expected_effect}

Return strict JSON only:
{{"sources": "paragraph 1", "reasoning": "paragraph 2"}}
"""
    try:
        response = await openai_client.responses.create(
            model=model,
            input=prompt,
            temperature=0.3,
        )
        text = (response.output_text or "").strip()
        data = json.loads(text)
        return (
            data.get("sources"),
            data.get("reasoning"),
        )
    except Exception as e:
        logger.debug("Score explanation LLM failed: %s", e)
        return None, None


async def score_signal(
    signal: Signal,
    market_provider: MarketDataProvider,
    insight_provider: MarketInsightProvider,
    openai_client: Any = None,
    openai_model: str = "gpt-4o-mini",
    skip_explanations: bool = False,
    include_insight: bool = True,
    include_stock_market_data: bool = True,
) -> ScoreBreakdown:
    news_score = compute_news_score(signal)
    market_score, market_components, notes = await compute_market_score(
        signal, market_provider, include_stock_snapshots=include_stock_market_data
    )
    historical_score = compute_historical_score(signal)
    final_score = clamp(0.45 * news_score + 0.35 * market_score + 0.20 * historical_score)

    primary_symbol = signal.trade_ideas[0].symbol if signal.trade_ideas else None
    insight = None
    if include_insight and primary_symbol:
        try:
            insight = await asyncio.wait_for(
                insight_provider.insight(primary_symbol),
                timeout=INSIGHT_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            notes.append("Company fundamentals checks timed out, so earnings/beta overlays were skipped.")

    if market_components["breadth_confirmation"] is not None and market_components["breadth_confirmation"] < 0.4:
        final_score = clamp(final_score * 0.8)
        notes.append("The broader market isn't strongly confirming this yet. Proceed with caution.")

    if market_components["stock_relative_strength"] is not None and market_components["stock_relative_strength"] < 0.35:
        final_score = clamp(final_score * 0.85)
        notes.append("Current price action doesn't fully match this idea.")

    if insight is not None:
        if insight.days_to_earnings is not None and insight.days_to_earnings <= 7:
            final_score = clamp(final_score * 0.88)
            notes.append(f"Earnings in {insight.days_to_earnings} day(s) could overshadow this news.")
        if insight.market_cap is not None and insight.market_cap < 2_000_000_000:
            final_score = clamp(final_score * 0.9)
            notes.append("Smaller company. Higher risk, consider smaller position sizes.")
        if insight.beta is not None and insight.beta > 2.0:
            notes.append("This stock tends to swing more than the market. Expect bigger moves.")

    expl_sources, expl_reasoning = None, None
    if openai_client and not skip_explanations:
        expl_sources, expl_reasoning = await _generate_score_explanations(
            signal, news_score, market_score, historical_score, final_score,
            market_components, notes, openai_client, openai_model,
        )

    return ScoreBreakdown(
        news_score=round(news_score, 3),
        market_score=round(market_score, 3),
        historical_score=round(historical_score, 3),
        final_score=round(final_score, 3),
        label=confidence_label(final_score),
        primary_symbol=primary_symbol,
        sector_etf=market_components["sector_etf"],
        market_data_source=market_components["market_data_source"],
        insight_data_source=insight.provider_name if insight else None,
        market_cap=insight.market_cap if insight else None,
        beta=insight.beta if insight else None,
        days_to_earnings=insight.days_to_earnings if insight else None,
        sector_relative_strength=market_components["sector_relative_strength"],
        stock_relative_strength=market_components["stock_relative_strength"],
        volume_confirmation=market_components["volume_confirmation"],
        breadth_confirmation=market_components["breadth_confirmation"],
        volatility_alignment=market_components["volatility_alignment"],
        notes=notes,
        score_explanation_news=None,
        score_explanation_market=None,
        score_explanation_history=None,
        sources_explanation=expl_sources,
        reasoning_explanation=expl_reasoning,
    )
