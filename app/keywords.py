"""Generate sector search keywords and article relevance signals."""

from __future__ import annotations

import re

from openai import AsyncOpenAI

from app.config import current_time_context
from app.sectors import SectorDefinition, get_expanded_keywords, get_sector, normalize_sector_key


BROAD_TERM_BLOCKLIST: frozenset[str] = frozenset({"or", "and", "go", "market", "sector"})


class KeywordGenerator:
    """Generate search keywords from a sector definition."""

    def __init__(self, openai_api_key: str | None = None, model: str = "gpt-4o-mini"):
        self.model = model
        self.client = AsyncOpenAI(api_key=openai_api_key) if openai_api_key else None

    def static_query(self, sector: SectorDefinition) -> str:
        """Fast static keywords from seed_keywords. No API call."""
        return self._static_generate(sector)

    async def generate_for_sector(self, sector: SectorDefinition) -> str:
        if self.client:
            query = await self._ai_generate(sector)
            if query:
                return query
        return self._static_generate(sector)

    def _static_generate(self, sector: SectorDefinition) -> str:
        # Use expanded keywords (seeds + synonyms) for 3–5x recall boost; fallback to seeds for custom
        phrases = get_expanded_keywords(sector.key) or sector.seed_keywords
        seen: set[str] = set()
        out: list[str] = []
        for phrase in phrases:
            k = phrase.lower()
            if k not in seen:
                seen.add(k)
                out.append(phrase)
            if len(out) >= 14:
                break
        return " OR ".join(out[:14]) if out else sector.display_name

    async def _ai_generate(self, sector: SectorDefinition) -> str | None:
        prompt = f"""You are a macro market news search assistant.
Generate 8-12 targeted search keywords or phrases for this sector.
Focus on tradable macro, supply chain, policy, rates, commodity, and geopolitical angles.
Return ONLY one line suitable for a NewsAPI q parameter, using OR between terms.

Current date and time: {current_time_context()}

Sector: {sector.display_name}
Category: {sector.category}
Seed keywords: {", ".join(sector.seed_keywords)}

Example output:
semiconductor OR chip export controls OR foundry capacity OR AI chip demand OR TSMC"""
        try:
            response = await self.client.responses.create(
                model=self.model,
                input=prompt,
                temperature=0.2,
            )
            text = (response.output_text or "").strip()
            return text if text else None
        except Exception:
            return None


def extract_filter_keywords(query: str) -> list[str]:
    parts = re.split(r"\s+OR\s+", query, flags=re.IGNORECASE)
    return [
        p.strip()
        for p in parts
        if p.strip() and p.strip().lower() not in BROAD_TERM_BLOCKLIST
    ]


def _keyword_in_text(kw: str, text: str) -> bool:
    """Match keyword with word boundaries for short terms (avoid 'ai' matching 'chain')."""
    kw_lower = kw.lower()
    if len(kw_lower) <= 3:
        return bool(re.search(r"\b" + re.escape(kw_lower) + r"\b", text))
    return kw_lower in text


def is_relevant_to_keywords(article_title: str, article_description: str | None, keywords: list[str]) -> bool:
    if not keywords:
        return True
    text = f"{article_title} {article_description or ''}".lower()
    return any(_keyword_in_text(kw, text) for kw in keywords)


def matched_keywords(article_title: str, article_description: str | None, keywords: list[str]) -> list[str]:
    text = f"{article_title} {article_description or ''}".lower()
    return [kw for kw in keywords if _keyword_in_text(kw, text)]


def sector_from_value(value: str) -> SectorDefinition | None:
    return get_sector(normalize_sector_key(value))
