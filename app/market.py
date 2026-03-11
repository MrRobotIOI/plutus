from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from time import time

import httpx

from app.models import TradeIdea
from app.sectors import SECTOR_TO_ETF

logger = logging.getLogger("plutus.market")

# Polygon free tier: 5 requests/minute. Shared limiter for all Polygon calls.
_POLYGON_LIMITER: asyncio.Lock | None = None
_POLYGON_REQUEST_TIMES: list[float] = []
_POLYGON_MAX_PER_MINUTE = 5


# Fallback map for sectors not in SECTOR_TO_ETF (e.g. before sectors load)
SECTOR_ETF_MAP: dict[str, str] = {
    "energy": "XLE",
    "financials": "XLF",
    "semiconductors": "SMH",
    "shipping": "IYT",
    "defense": "ITA",
    "healthcare": "XLV",
    "utilities": "XLU",
    "space": "ARKX",
    "fertilizers": "MOO",
    "uranium": "URA",
    "carbon_markets": "KRBN",
    "data_centers": "SRVR",
    "water": "PHO",
    "rare_earths": "REMX",
    "drones": "ITA",
    "battery_materials": "LIT",
    "reinsurance": "KIE",
    "crypto": "IBIT",
    "ai": "XLK",
    "cybersecurity": "HACK",
    "cloud_computing": "XLK",
    "ev": "QCLN",
    "solar": "TAN",
    "hydrogen": "ICLN",
    "ecommerce": "IBUY",
    "airlines": "JETS",
    "logistics": "IYT",
    "biotech": "XBI",
    "mining": "XLB",
    "copper": "CPER",
    "steel": "SLX",
    "rail": "IYT",
    "streaming": "NETF",
    "fintech": "IPAY",
    "payments": "IPAY",
    "oil_services": "OIH",
    "natural_gas": "XLE",
    "robotics": "BOTZ",
    "saas": "IGV",
}

BENCHMARK_SYMBOL = "SPY"


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    day_return: float | None
    five_day_return: float | None
    volume_ratio: float | None
    intraday_range_ratio: float | None
    provider_name: str | None = None


@dataclass(frozen=True)
class SymbolInsight:
    symbol: str
    market_cap: float | None
    beta: float | None
    average_volume: float | None
    next_earnings_at: datetime | None
    days_to_earnings: int | None
    provider_name: str


class MarketDataProvider:
    name = "market"

    async def snapshot(self, symbol: str) -> MarketSnapshot | None:
        raise NotImplementedError


class NeutralMarketDataProvider(MarketDataProvider):
    name = "neutral"

    async def snapshot(self, symbol: str) -> MarketSnapshot | None:
        return None


class FinnhubMarketDataProvider(MarketDataProvider):
    name = "finnhub"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._cache: dict[str, MarketSnapshot | None] = {}

    async def snapshot(self, symbol: str) -> MarketSnapshot | None:
        if symbol in self._cache:
            return self._cache[symbol]

        now = int(time())
        start = now - 40 * 24 * 60 * 60
        url = "https://finnhub.io/api/v1/stock/candle"
        params = {
            "symbol": symbol,
            "resolution": "D",
            "from": start,
            "to": now,
            "token": self.api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=12) as client:
                response = await client.get(url, params=params)
                if response.status_code == 403:
                    logger.debug("Finnhub 403 for %s (free tier may restrict stock/candle)", symbol)
                    self._cache[symbol] = None
                    return None
                response.raise_for_status()
                payload = response.json()
        except httpx.HTTPStatusError:
            self._cache[symbol] = None
            return None
        except Exception:
            self._cache[symbol] = None
            return None

        closes = payload.get("c") or []
        highs = payload.get("h") or []
        lows = payload.get("l") or []
        volumes = payload.get("v") or []
        if len(closes) < 2:
            self._cache[symbol] = None
            return None

        day_return = (closes[-1] / closes[-2] - 1.0) if closes[-2] else None
        five_day_return = (closes[-1] / closes[-6] - 1.0) if len(closes) >= 6 and closes[-6] else None
        avg_volume = sum(volumes[-21:-1]) / len(volumes[-21:-1]) if len(volumes) >= 21 else None
        volume_ratio = (volumes[-1] / avg_volume) if avg_volume and avg_volume > 0 else None
        intraday_range_ratio = ((highs[-1] - lows[-1]) / closes[-1]) if highs and lows and closes[-1] else None

        snapshot = MarketSnapshot(
            symbol=symbol,
            day_return=day_return,
            five_day_return=five_day_return,
            volume_ratio=volume_ratio,
            intraday_range_ratio=intraday_range_ratio,
            provider_name=self.name,
        )
        self._cache[symbol] = snapshot
        return snapshot


async def _polygon_rate_limit() -> None:
    """Enforce Polygon free tier: 5 requests per minute."""
    global _POLYGON_LIMITER, _POLYGON_REQUEST_TIMES
    if _POLYGON_LIMITER is None:
        _POLYGON_LIMITER = asyncio.Lock()
    async with _POLYGON_LIMITER:
        now = time()
        # Drop requests older than 60 seconds
        _POLYGON_REQUEST_TIMES[:] = [t for t in _POLYGON_REQUEST_TIMES if now - t < 60]
        while len(_POLYGON_REQUEST_TIMES) >= _POLYGON_MAX_PER_MINUTE:
            wait = 60 - (now - _POLYGON_REQUEST_TIMES[0])
            if wait > 0:
                logger.debug("Polygon rate limit: waiting %.1fs", wait)
                await asyncio.sleep(wait)
            _POLYGON_REQUEST_TIMES.pop(0)
            now = time()
        _POLYGON_REQUEST_TIMES.append(time())


class PolygonMarketDataProvider(MarketDataProvider):
    name = "polygon"

    def __init__(self, api_key: str, base_url: str = "https://api.polygon.io"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._cache: dict[str, MarketSnapshot | None] = {}

    async def snapshot(self, symbol: str) -> MarketSnapshot | None:
        if symbol in self._cache:
            return self._cache[symbol]

        await _polygon_rate_limit()

        end_date = datetime.now(timezone.utc).date()
        start_date = end_date.fromordinal(end_date.toordinal() - 45)
        url = f"{self.base_url}/v2/aggs/ticker/{symbol}/range/1/day/{start_date.isoformat()}/{end_date.isoformat()}"
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 120,
            "apiKey": self.api_key,
        }
        payload = None
        for attempt in range(3):
            if attempt > 0:
                await _polygon_rate_limit()
            try:
                async with httpx.AsyncClient(timeout=12) as client:
                    response = await client.get(url, params=params)
                    if response.status_code == 429:
                        backoff = 2 ** attempt
                        logger.warning("Polygon 429 rate limit, retry in %ds", backoff)
                        await asyncio.sleep(backoff)
                        continue
                    response.raise_for_status()
                    payload = response.json()
                    break
            except httpx.HTTPStatusError:
                self._cache[symbol] = None
                return None
            except Exception:
                self._cache[symbol] = None
                return None
        if payload is None:
            self._cache[symbol] = None
            return None

        rows = payload.get("results") or []
        if len(rows) < 2:
            self._cache[symbol] = None
            return None

        closes = [row.get("c") for row in rows]
        highs = [row.get("h") for row in rows]
        lows = [row.get("l") for row in rows]
        volumes = [row.get("v") for row in rows]
        if not closes[-1] or not closes[-2]:
            self._cache[symbol] = None
            return None

        day_return = closes[-1] / closes[-2] - 1.0
        five_day_return = closes[-1] / closes[-6] - 1.0 if len(closes) >= 6 and closes[-6] else None
        trailing_volumes = [value for value in volumes[-21:-1] if value is not None]
        avg_volume = sum(trailing_volumes) / len(trailing_volumes) if trailing_volumes else None
        volume_ratio = (volumes[-1] / avg_volume) if avg_volume and volumes[-1] else None
        intraday_range_ratio = ((highs[-1] - lows[-1]) / closes[-1]) if highs[-1] and lows[-1] and closes[-1] else None

        snapshot = MarketSnapshot(
            symbol=symbol,
            day_return=day_return,
            five_day_return=five_day_return,
            volume_ratio=volume_ratio,
            intraday_range_ratio=intraday_range_ratio,
            provider_name=self.name,
        )
        self._cache[symbol] = snapshot
        return snapshot


def _yfinance_snapshot_sync(symbol: str) -> MarketSnapshot | None:
    """Synchronous yfinance fetch for market snapshot. Runs in thread pool."""
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="2mo", interval="1d")
        if hist is None or len(hist) < 2:
            return None
        closes = hist["Close"].tolist()
        highs = hist["High"].tolist()
        lows = hist["Low"].tolist()
        volumes = hist["Volume"].tolist()
        if not closes or not closes[-1] or not closes[-2]:
            return None
        day_return = closes[-1] / closes[-2] - 1.0
        five_day_return = (
            (closes[-1] / closes[-6] - 1.0) if len(closes) >= 6 and closes[-6] else None
        )
        trailing_volumes = [
            v for v in volumes[-21:-1]
            if v is not None and (not isinstance(v, float) or v == v)
        ]
        avg_volume = sum(trailing_volumes) / len(trailing_volumes) if trailing_volumes else None
        volume_ratio = (
            (volumes[-1] / avg_volume) if avg_volume and volumes[-1] else None
        )
        intraday_range_ratio = (
            (highs[-1] - lows[-1]) / closes[-1]
            if highs and lows and closes[-1]
            else None
        )
        return MarketSnapshot(
            symbol=symbol,
            day_return=day_return,
            five_day_return=five_day_return,
            volume_ratio=volume_ratio,
            intraday_range_ratio=intraday_range_ratio,
            provider_name="yfinance",
        )
    except Exception as e:
        logger.debug("yfinance snapshot failed for %s: %s", symbol, e)
        return None


class YFinanceMarketDataProvider(MarketDataProvider):
    """Free market data via Yahoo Finance. No API key required."""

    name = "yfinance"

    def __init__(self):
        self._cache: dict[str, MarketSnapshot | None] = {}
        self._pending: dict[str, asyncio.Task] = {}

    async def snapshot(self, symbol: str) -> MarketSnapshot | None:
        if symbol in self._cache:
            return self._cache[symbol]
        if symbol in self._pending:
            return await self._pending[symbol]

        async def _fetch() -> MarketSnapshot | None:
            snap = await asyncio.to_thread(_yfinance_snapshot_sync, symbol)
            self._cache[symbol] = snap
            return snap

        task = asyncio.create_task(_fetch())
        self._pending[symbol] = task
        try:
            return await task
        finally:
            del self._pending[symbol]


class CompositeMarketDataProvider(MarketDataProvider):
    name = "composite"

    def __init__(self, providers: list[MarketDataProvider]):
        self.providers = providers
        self._cache: dict[str, MarketSnapshot | None] = {}

    async def snapshot(self, symbol: str) -> MarketSnapshot | None:
        if symbol in self._cache:
            return self._cache[symbol]
        for provider in self.providers:
            snapshot = await provider.snapshot(symbol)
            if snapshot is not None:
                self._cache[symbol] = snapshot
                return snapshot
        self._cache[symbol] = None
        return None


class MarketInsightProvider:
    name = "insight"

    async def insight(self, symbol: str) -> SymbolInsight | None:
        raise NotImplementedError


class NeutralMarketInsightProvider(MarketInsightProvider):
    name = "neutral"

    async def insight(self, symbol: str) -> SymbolInsight | None:
        return None


def _yfinance_insight_sync(symbol: str) -> SymbolInsight | None:
    """Synchronous yfinance fetch for company insight. Runs in thread pool."""
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        info = ticker.info
        if not info:
            return None
        market_cap = info.get("marketCap")
        beta = info.get("beta")
        avg_vol = info.get("averageVolume")
        next_earnings_at = None
        days_to_earnings = None
        try:
            earnings_df = ticker.get_earnings_dates(limit=12)
            if earnings_df is not None and not earnings_df.empty:
                now = datetime.now(timezone.utc)
                for idx in earnings_df.index:
                    if hasattr(idx, "to_pydatetime"):
                        dt = idx.to_pydatetime()
                    else:
                        continue
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    delta = (dt - now).days
                    if delta >= 0:
                        next_earnings_at = dt
                        days_to_earnings = delta
                        break
        except Exception:
            pass
        return SymbolInsight(
            symbol=symbol,
            market_cap=float(market_cap) if market_cap is not None else None,
            beta=float(beta) if beta is not None else None,
            average_volume=float(avg_vol) if avg_vol is not None else None,
            next_earnings_at=next_earnings_at,
            days_to_earnings=days_to_earnings,
            provider_name="yfinance",
        )
    except Exception as e:
        logger.debug("yfinance insight failed for %s: %s", symbol, e)
        return None


class YFinanceMarketInsightProvider(MarketInsightProvider):
    """Free company profile and earnings via Yahoo Finance. No API key required."""

    name = "yfinance"

    def __init__(self):
        self._cache: dict[str, SymbolInsight | None] = {}

    async def insight(self, symbol: str) -> SymbolInsight | None:
        if symbol in self._cache:
            return self._cache[symbol]
        insight = await asyncio.to_thread(_yfinance_insight_sync, symbol)
        self._cache[symbol] = insight
        return insight


class FMPMarketInsightProvider(MarketInsightProvider):
    name = "fmp"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._cache: dict[str, SymbolInsight | None] = {}

    async def insight(self, symbol: str) -> SymbolInsight | None:
        if symbol in self._cache:
            return self._cache[symbol]

        profile_url = "https://financialmodelingprep.com/stable/profile"
        earnings_url = "https://financialmodelingprep.com/stable/earnings"
        params = {"symbol": symbol, "apikey": self.api_key}

        profile = None
        earnings_items: list[dict] = []
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                profile_resp = await client.get(profile_url, params=params)
                profile_resp.raise_for_status()
                profile_payload = profile_resp.json()
                if isinstance(profile_payload, list) and profile_payload:
                    profile = profile_payload[0]
                elif isinstance(profile_payload, dict):
                    profile = profile_payload
        except Exception:
            profile = None

        try:
            async with httpx.AsyncClient(timeout=12) as client:
                earnings_resp = await client.get(earnings_url, params=params)
                if earnings_resp.status_code == 402:
                    logger.debug("FMP earnings 402 (requires paid plan), using profile only")
                    earnings_items = []
                else:
                    earnings_resp.raise_for_status()
                    earnings_payload = earnings_resp.json()
                    if isinstance(earnings_payload, list):
                        earnings_items = earnings_payload
                    elif isinstance(earnings_payload, dict):
                        earnings_items = earnings_payload.get("earnings", []) or earnings_payload.get("data", []) or []
        except Exception:
            earnings_items = []

        next_earnings_at = None
        days_to_earnings = None
        now = datetime.now(timezone.utc)
        for item in earnings_items:
            raw_date = item.get("date") or item.get("fiscalDateEnding") or item.get("earningsAnnouncement")
            if not raw_date:
                continue
            try:
                parsed = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            delta_days = (parsed - now).days
            if delta_days >= 0:
                next_earnings_at = parsed
                days_to_earnings = delta_days
                break

        insight = SymbolInsight(
            symbol=symbol,
            market_cap=(profile or {}).get("mktCap"),
            beta=(profile or {}).get("beta"),
            average_volume=(profile or {}).get("volAvg"),
            next_earnings_at=next_earnings_at,
            days_to_earnings=days_to_earnings,
            provider_name=self.name,
        )
        self._cache[symbol] = insight
        return insight


class PolygonMarketInsightProvider(MarketInsightProvider):
    """Company profile via Polygon/Massive ticker reference API. Fast REST, no scraping."""

    name = "polygon"

    def __init__(self, api_key: str, base_url: str = "https://api.polygon.io"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._cache: dict[str, SymbolInsight | None] = {}

    async def insight(self, symbol: str) -> SymbolInsight | None:
        if symbol in self._cache:
            return self._cache[symbol]

        await _polygon_rate_limit()

        url = f"{self.base_url}/v3/reference/tickers/{symbol}"
        params = {"apiKey": self.api_key}
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(url, params=params)
                if response.status_code == 429:
                    logger.debug("Polygon insight 429 rate limit for %s", symbol)
                    self._cache[symbol] = None
                    return None
                response.raise_for_status()
                payload = response.json()
        except Exception as e:
            logger.debug("Polygon insight failed for %s: %s", symbol, e)
            self._cache[symbol] = None
            return None

        results = payload.get("results")
        if not results:
            self._cache[symbol] = None
            return None

        market_cap = results.get("market_cap")
        insight = SymbolInsight(
            symbol=symbol,
            market_cap=float(market_cap) if market_cap is not None else None,
            beta=None,
            average_volume=None,
            next_earnings_at=None,
            days_to_earnings=None,
            provider_name=self.name,
        )
        self._cache[symbol] = insight
        return insight


class CompositeMarketInsightProvider(MarketInsightProvider):
    name = "composite"

    def __init__(self, providers: list[MarketInsightProvider]):
        self.providers = providers
        self._cache: dict[str, SymbolInsight | None] = {}

    async def insight(self, symbol: str) -> SymbolInsight | None:
        if symbol in self._cache:
            return self._cache[symbol]
        for provider in self.providers:
            insight = await provider.insight(symbol)
            if insight is not None:
                self._cache[symbol] = insight
                return insight
        self._cache[symbol] = None
        return None


def sector_etf_for(sector_key: str) -> str:
    return SECTOR_TO_ETF.get(sector_key) or SECTOR_ETF_MAP.get(sector_key, BENCHMARK_SYMBOL)


def representative_symbols(trade_ideas: list[TradeIdea], limit: int = 3) -> list[tuple[str, str]]:
    seen: set[str] = set()
    picks: list[tuple[str, str]] = []
    for idea in trade_ideas:
        if idea.symbol not in seen:
            seen.add(idea.symbol)
            picks.append((idea.symbol, idea.side))
        if len(picks) >= limit:
            break
    return picks
