from __future__ import annotations

import json
import logging
import re

from openai import AsyncOpenAI

from app.config import current_time_context
from app.models import EventType, NewsArticle, StructuredEvent
from app.sectors import (
    COMPANY_SECTOR_MAP,
    SECTOR_TO_EVENT_TYPE,
    SECTOR_UNIVERSE,
    get_expanded_keywords,
)

logger = logging.getLogger("plutus.event_detector")

# Keyword hit thresholds
WEAK_THRESHOLD = 1
STRONG_THRESHOLD = 2
COMPANY_BONUS = 2
MAX_SECTORS_AFFECTED = 6

# Event type → default summary, commodities, expected_effect
_EVENT_DEFAULTS: dict[EventType, tuple[str, list[str], str]] = {
    EventType.OIL_SUPPLY_SHOCK: (
        "Potential oil or gas supply constraint",
        ["oil", "natural gas"],
        "oil supply down -> oil and gas prices up",
    ),
    EventType.GOVERNMENT_STIMULUS: (
        "Government stimulus likely to boost cyclical demand",
        ["copper", "steel", "cement"],
        "demand increase for cyclical sectors and industrial commodities",
    ),
    EventType.RATE_HIKE: (
        "Monetary policy shift detected",
        [],
        "rate changes support financials and pressure duration-sensitive sectors",
    ),
    EventType.SHIPPING_DISRUPTION: (
        "Trade route disruption increases transport costs",
        ["oil"],
        "shipping costs up, oil logistics risk up, supply chains slow",
    ),
    EventType.SANCTIONS: (
        "Trade restrictions or strategic supply chain pressure detected",
        ["oil", "metals", "rare earths"],
        "restricted supply chains drive price volatility and sector dispersion",
    ),
    EventType.NATURAL_DISASTER: (
        "Disaster may disrupt production, utilities, or agriculture",
        ["wheat", "corn"],
        "temporary supply disruption and damage-related costs",
    ),
    EventType.OTHER: (
        "Market-relevant catalyst detected",
        [],
        "sector-specific news may affect related equities",
    ),
}

GENERIC_FALLBACK_KEYWORDS = (
    "economy", "markets", "recession", "gdp", "inflation", "geopolitic",
    "trade", "commodit", "rare earth", "power demand", "data center", "electric grid",
)


def _keyword_in_text(kw: str, text: str) -> bool:
    """Match keyword with word boundaries for short terms to reduce false positives."""
    kw_lower = kw.lower()
    if len(kw_lower) <= 3:
        return bool(re.search(r"\b" + re.escape(kw_lower) + r"\b", text))
    return kw_lower in text


class EventDetector:
    def __init__(self, openai_api_key: str | None = None, model: str = "gpt-4o-mini"):
        self.model = model
        self.client = AsyncOpenAI(api_key=openai_api_key) if openai_api_key else None

    async def detect(self, article: NewsArticle) -> StructuredEvent | None:
        return self._heuristic_extract(article)

    async def detect_ai(self, article: NewsArticle) -> StructuredEvent | None:
        """AI-powered detection. Use selectively (e.g. top signal enrichment)."""
        if self.client is None:
            return self._heuristic_extract(article)
        prompt = self._build_prompt(article)
        try:
            response = await self.client.responses.create(
                model=self.model,
                input=prompt,
                temperature=0.1,
            )
            text = (response.output_text or "").strip()
            data = json.loads(text)
            event = StructuredEvent(**data)
            if not event.source_publication:
                event = event.model_copy(update={"source_publication": article.source})
            return event
        except Exception as e:
            logger.debug("OpenAI parse fallback for %r: %s", article.title[:50], e)
            return self._heuristic_extract(article)

    def _build_prompt(self, article: NewsArticle) -> str:
        return f"""
You are an economic event extraction engine.
Extract ONE macro-relevant event from this article and return STRICT JSON only.

Current date and time: {current_time_context()}

Allowed event_type values:
oil_supply_shock, government_stimulus, rate_hike, shipping_disruption, sanctions, natural_disaster, other

JSON schema:
{{
  "event_type": "oil_supply_shock",
  "region": "middle east",
  "summary": "Short summary",
  "sectors_affected": ["energy"],
  "commodities": ["oil"],
  "expected_effect": "oil supply down, oil prices up",
  "confidence": 0.65,
  "horizon": "1-3 weeks",
  "source_title": "article title",
  "source_url": "https://...",
  "source_publication": "Reuters"
}}

Article source: {article.source}
Article title: {article.title}
Article description: {article.description or ""}
Article content: {article.content or ""}
"""

    def _heuristic_extract(self, article: NewsArticle) -> StructuredEvent | None:
        text = f"{article.title} {article.description or ''} {article.content or ''}".lower()
        source_url = article.url or ""

        # 1. Dynamic sector scan: score each sector by keyword hits
        sector_scores: dict[str, int] = {}
        for sector_key, sector in SECTOR_UNIVERSE.items():
            keywords = get_expanded_keywords(sector_key)
            if not keywords:
                continue
            hits = sum(1 for kw in keywords if _keyword_in_text(kw, text))
            if hits >= WEAK_THRESHOLD:
                sector_scores[sector_key] = sector_scores.get(sector_key, 0) + hits

        # 2. Company detection: bonus for sectors when company names appear
        for company, sector_key in COMPANY_SECTOR_MAP.items():
            if _keyword_in_text(company, text):
                sector_scores[sector_key] = sector_scores.get(sector_key, 0) + COMPANY_BONUS

        # 3. Fallback: generic macro keywords → OTHER
        if not sector_scores and any(k in text for k in GENERIC_FALLBACK_KEYWORDS):
            summary = article.title[:120] + ("..." if len(article.title) > 120 else "")
            return StructuredEvent(
                event_type=EventType.OTHER,
                region="global",
                summary=summary,
                sectors_affected=["financials", "utilities", "materials"],
                commodities=[],
                expected_effect="macro event may affect broad market sentiment and cyclicals",
                confidence=0.5,
                horizon="1-4 weeks",
                source_title=article.title,
                source_url=source_url,
                source_publication=article.source,
            )

        if not sector_scores:
            return None

        # 4. Top sectors by score (strong signal = 2+ hits)
        sorted_sectors = sorted(
            sector_scores.items(),
            key=lambda x: (-x[1], x[0]),
        )
        sectors_affected = [s for s, _ in sorted_sectors[:MAX_SECTORS_AFFECTED]]
        top_sector = sectors_affected[0]
        top_score = sector_scores[top_sector]

        # 5. Event type from top sector
        event_type = SECTOR_TO_EVENT_TYPE.get(top_sector, EventType.OTHER)

        # 6. Confidence: weak (1 hit) vs strong (2+)
        confidence = 0.55 if top_score >= STRONG_THRESHOLD else 0.52

        summary, commodities, expected_effect = _EVENT_DEFAULTS[event_type]

        return StructuredEvent(
            event_type=event_type,
            region="global",
            summary=summary,
            sectors_affected=sectors_affected,
            commodities=commodities,
            expected_effect=expected_effect,
            confidence=confidence,
            horizon="1-4 weeks",
            source_title=article.title,
            source_url=source_url,
            source_publication=article.source,
        )
