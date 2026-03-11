import os
from dataclasses import dataclass
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()


def current_time_context() -> str:
    """Return current date/time for LLM prompts so they know what 'now' is."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d, %H:%M UTC (%A)")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_key(name: str) -> str | None:
    v = os.getenv(name)
    return v.strip() if isinstance(v, str) and v.strip() else None


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None = _env_key("OPENAI_API_KEY")
    newsapi_key: str | None = _env_key("NEWSAPI_KEY")
    finnhub_key: str | None = _env_key("FINNHUB_API_KEY")
    polygon_key: str | None = _env_key("POLYGON_API_KEY") or _env_key("MASSIVE_API_KEY")
    polygon_base_url: str = (
        os.getenv("POLYGON_BASE_URL") or os.getenv("MASSIVE_BASE_URL") or "https://api.polygon.io"
    ).rstrip("/")
    fmp_key: str | None = _env_key("FMP_API_KEY")
    tavily_key: str | None = _env_key("TAVILY_API_KEY")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    plutus_max_articles: int = _env_int("PLUTUS_MAX_ARTICLES", 12)
    news_cache_minutes: int = _env_int("PLUTUS_NEWS_CACHE_MINUTES", 180)  # 3 hours default
    scan_cache_minutes: int = _env_int("PLUTUS_SCAN_CACHE_MINUTES", 180)  # 3 hours default
    # Daily precomputed scan (homepage): large scan once per 24h
    # In prod: runs automatically. In dev: manual trigger only (POST /api/v1/daily/trigger)
    daily_scan_sectors: int = _env_int("PLUTUS_DAILY_SCAN_SECTORS", 45)
    daily_scan_articles: int = _env_int("PLUTUS_DAILY_SCAN_ARTICLES", 12)
    # PLUTUS_ENV=prod|dev — prod: auto daily scan; dev: manual only
    env: str = (os.getenv("PLUTUS_ENV") or "dev").lower().strip()
    # Subscription: Stripe checkout URL for premium (set STRIPE_CHECKOUT_URL in env)
    stripe_checkout_url: str | None = _env_key("STRIPE_CHECKOUT_URL")
    # Scan speed: skip LLM score explanations, skip insight (earnings/mcap), limit symbol discovery
    skip_score_explanations: bool = os.getenv("PLUTUS_SKIP_SCORE_EXPLANATIONS", "1") == "1"
    include_insight: bool = os.getenv("PLUTUS_INCLUDE_INSIGHT", "0") == "1"
    symbol_discovery_limit: int = _env_int("PLUTUS_SYMBOL_DISCOVERY_LIMIT", 0)
    scan_concurrency: int = _env_int("PLUTUS_SCAN_CONCURRENCY", 4)
    default_max_sectors: int = _env_int("PLUTUS_DEFAULT_MAX_SECTORS", 6)
    default_max_articles: int = _env_int("PLUTUS_DEFAULT_MAX_ARTICLES", 8)
    # Fast scan: skip market fetches, use 4 sectors/4 articles. Target <30s.
    fast_scan: bool = os.getenv("PLUTUS_FAST_SCAN", "1") == "1"
    fast_scan_sectors: int = _env_int("PLUTUS_FAST_SCAN_SECTORS", 4)
    fast_scan_articles: int = _env_int("PLUTUS_FAST_SCAN_ARTICLES", 4)
    # Skip per-stock market fetches; use only SPY + sector ETF (saves ~50 yfinance calls per scan)
    include_stock_market_data: bool = os.getenv("PLUTUS_INCLUDE_STOCK_MARKET_DATA", "0") == "1"


settings = Settings()
