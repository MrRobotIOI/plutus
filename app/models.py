from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class EventType(str, Enum):
    OIL_SUPPLY_SHOCK = "oil_supply_shock"
    GOVERNMENT_STIMULUS = "government_stimulus"
    RATE_HIKE = "rate_hike"
    SHIPPING_DISRUPTION = "shipping_disruption"
    SANCTIONS = "sanctions"
    NATURAL_DISASTER = "natural_disaster"
    OTHER = "other"


class NewsArticle(BaseModel):
    source: str
    title: str
    description: str | None = None
    url: str | None = None
    published_at: datetime | None = None
    content: str | None = None
    query_used: str | None = None
    sector_key: str | None = None


class StructuredEvent(BaseModel):
    event_type: EventType
    region: str | None = None
    summary: str
    sectors_affected: list[str] = Field(default_factory=list)
    commodities: list[str] = Field(default_factory=list)
    expected_effect: str
    confidence: float = Field(ge=0.0, le=1.0)
    horizon: str = "1-3 weeks"
    source_title: str
    source_url: str | None = None
    source_publication: str | None = None


class SectorImpact(BaseModel):
    sector: str
    direction: Literal["bullish", "bearish"]
    rationale: str


class TradeIdea(BaseModel):
    side: Literal["LONG", "SHORT"]
    symbol: str
    sector: str
    rationale: str


class ScoreBreakdown(BaseModel):
    news_score: float
    market_score: float
    historical_score: float
    final_score: float
    label: str
    primary_symbol: str | None = None
    sector_etf: str | None = None
    market_data_source: str | None = None
    insight_data_source: str | None = None
    market_cap: float | None = None
    beta: float | None = None
    days_to_earnings: int | None = None
    sector_relative_strength: float | None = None
    stock_relative_strength: float | None = None
    volume_confirmation: float | None = None
    breadth_confirmation: float | None = None
    volatility_alignment: float | None = None
    notes: list[str] = Field(default_factory=list)
    # LLM-generated tailored explanations (when OpenAI is available)
    score_explanation_news: str | None = None
    score_explanation_market: str | None = None
    score_explanation_history: str | None = None
    # Sources + reasoning (preferred over methodology when set)
    sources_explanation: str | None = None
    reasoning_explanation: str | None = None


class Signal(BaseModel):
    event: StructuredEvent
    impacts: list[SectorImpact]
    trade_ideas: list[TradeIdea]
    risk_level: Literal["low", "medium", "high"]
    published_at: datetime | None = None
    matched_keywords: list[str] = Field(default_factory=list)
    sector_key: str | None = None
    sector_display_name: str | None = None
    source_count: int = 1
    score: ScoreBreakdown | None = None


class KeywordsRequest(BaseModel):
    sectors: list[str] = Field(default_factory=list)


class SectorScanRequest(BaseModel):
    watchlist: list[str] = Field(default_factory=list)
    max_articles_per_sector: int = 12
    max_sectors: int = 12


class EventCluster(BaseModel):
    cluster_label: str
    event_type: EventType
    signal_count: int
    source_count: int
    top_signal: Signal
    signals: list[Signal]


class SectorGroup(BaseModel):
    sector_key: str
    sector_display_name: str
    category: str
    matched_keywords: list[str] = Field(default_factory=list)
    source_count: int
    strongest_cluster: str | None = None
    top_trade_ideas: list[TradeIdea] = Field(default_factory=list)
    event_clusters: list[EventCluster] = Field(default_factory=list)


class GroupedRunResponse(BaseModel):
    generated_at: datetime
    sectors_scanned: list[str]
    sector_groups: list[SectorGroup]


class RunRequest(BaseModel):
    query: str | None = None
    sectors: list[str] = Field(default_factory=list)
    max_articles: int = 5


class RunResponse(BaseModel):
    generated_at: datetime
    signals: list[Signal]
    query_used: str | None = None
