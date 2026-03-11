"""LLM + web search for symbol discovery and rationale generation. Replaces cached sector maps."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass

from app.config import current_time_context
from app.models import SectorImpact, StructuredEvent, TradeIdea

logger = logging.getLogger("plutus.symbol_discovery")

MAX_SYMBOLS_PER_IMPACT = 6
MAX_SEARCH_RESULTS = 12
_BAD_SYMBOLS = frozenset({"AI", "OR", "AND", "USD", "NEWS", "ETF", "IPO", "CEO", "FDA"})


@dataclass
class DiscoveredImpact:
    sector: str
    direction: str
    rationale: str
    symbols: list[str]


def _search_duckduckgo(query: str, max_results: int = MAX_SEARCH_RESULTS) -> list[dict]:
    """Sync DuckDuckGo search. Run in thread to avoid blocking."""
    try:
        from duckduckgo_search import DDGS

        results = list(DDGS().text(query, region="us-en", max_results=max_results))
        return [{"title": r.get("title", ""), "body": r.get("body", "")} for r in results]
    except ImportError:
        logger.debug("duckduckgo-search not installed; run: pip install duckduckgo-search")
        return []
    except Exception as e:
        logger.debug("DuckDuckGo search failed: %s", e)
        return []


async def web_search(query: str, max_results: int = MAX_SEARCH_RESULTS) -> list[dict]:
    """Search the web for market-relevant content. Uses DuckDuckGo (no API key)."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _search_duckduckgo, query, max_results)


def _build_search_query(event: StructuredEvent, sector: str) -> str:
    """Build a search query to find stocks affected by this event + sector."""
    headline = (event.source_title or "")[:80]
    event_type = getattr(event.event_type, "value", str(event.event_type))
    # e.g. "financials stocks macro volatility Fed rates 2024"
    sector_display = sector.replace("_", " ")
    return f"{sector_display} stocks {headline} {event_type}"


async def _discover_one_impact(
    event: StructuredEvent,
    impact: SectorImpact,
    openai_client,
    model: str,
) -> DiscoveredImpact | None:
    """Process one sector impact: web search + LLM. Used for parallel execution."""
    query = _build_search_query(event, impact.sector)
    search_results = await web_search(query)
    snippets = "\n".join(
        f"- {r.get('title', '')}: {r.get('body', '')[:200]}"
        for r in search_results[:8]
    )
    search_context = snippets or "No web search results. Use your knowledge of this sector and current market to suggest relevant symbols."

    prompt = f"""You are helping an investor find stocks for a macro trade idea.

Current date and time: {current_time_context()}

News headline: {event.source_title[:120]}
Event type: {getattr(event.event_type, 'value', event.event_type)}
Expected effect: {event.expected_effect}
Sector: {impact.sector}

Web search results for "{query}":
{search_context}

Return JSON only:
1. "symbols": list of 4-6 US-listed ticker symbols (e.g. JPM, XOM) most relevant to this headline and sector. Prefer liquid names. No ETFs unless highly relevant.
2. "rationale": one short sentence (under 15 words) explaining why this sector matters for this news. Be specific to the headline, not generic.

Example: {{"symbols": ["JPM","BAC","GS"], "rationale": "Fed rate outlook supports bank net interest margins."}}

Return JSON only:"""

    try:
        response = await openai_client.responses.create(
            model=model,
            input=prompt,
            temperature=0.2,
        )
        text = (response.output_text or "").strip()
        json_match = re.search(r"\{[\s\S]*\}", text)
        if not json_match:
            return None
        data = json.loads(json_match.group())

        symbols_raw = data.get("symbols") or []
        symbols = []
        for s in symbols_raw:
            sym = str(s).upper().strip()
            if sym in _BAD_SYMBOLS or len(sym) > 6:
                continue
            if sym not in symbols:
                symbols.append(sym)
            if len(symbols) >= MAX_SYMBOLS_PER_IMPACT:
                break

        rationale = (data.get("rationale") or "").strip()
        if not rationale:
            rationale = f"{impact.sector.replace('_', ' ').title()} news may affect related equities."

        if symbols:
            return DiscoveredImpact(
                sector=impact.sector,
                direction=impact.direction,
                rationale=rationale,
                symbols=symbols,
            )
    except Exception as e:
        logger.debug("Symbol discovery failed for %s: %s", impact.sector, e)
    return None


async def discover_symbols_and_rationale(
    event: StructuredEvent,
    impacts: list[SectorImpact],
    openai_client,
    model: str = "gpt-4o-mini",
) -> list[DiscoveredImpact]:
    """
    Use web search + LLM to find symbols and generate rationale for each sector impact.
    No cached symbol maps. Returns list of (sector, direction, rationale, symbols).
    """
    if not openai_client or not impacts:
        return []

    results = await asyncio.gather(
        *[_discover_one_impact(event, imp, openai_client, model) for imp in impacts]
    )
    return [r for r in results if r is not None]


def build_trade_ideas_from_discovery(discovered: list[DiscoveredImpact]) -> list[TradeIdea]:
    """Convert discovered impacts to TradeIdeas."""
    ideas: list[TradeIdea] = []
    for d in discovered:
        side = "LONG" if d.direction == "bullish" else "SHORT"
        for symbol in d.symbols:
            ideas.append(
                TradeIdea(
                    side=side,
                    symbol=symbol,
                    sector=d.sector,
                    rationale=d.rationale,
                )
            )
    return ideas
