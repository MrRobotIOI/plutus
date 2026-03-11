from __future__ import annotations

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

import httpx

from app.models import NewsArticle

logger = logging.getLogger("plutus.news")

# NewsAPI free tier: 100 requests/day. Throttle to avoid 429.
_NEWSAPI_LIMITER: asyncio.Lock | None = None
_NEWSAPI_REQUEST_TIMES: list[float] = []
_NEWSAPI_MAX_PER_MINUTE = 5

# Shared fetch cache: (cache_key -> (articles, timestamp)), 3hr TTL, background refresh on hit
_FETCH_CACHE: dict[tuple, tuple[list[NewsArticle], float]] = {}
_FETCH_CACHE_LOCK = asyncio.Lock()
_REFRESH_IN_PROGRESS: set[tuple] = set()


async def _refresh_fetch_background(
    cache_key: tuple,
    fetch_fn: Callable[[], Awaitable[list[NewsArticle]]],
) -> None:
    """Run fetch in background and update cache. Prevents duplicate refreshes per key."""
    async with _FETCH_CACHE_LOCK:
        if cache_key in _REFRESH_IN_PROGRESS:
            return
        _REFRESH_IN_PROGRESS.add(cache_key)
    try:
        articles = await fetch_fn()
        async with _FETCH_CACHE_LOCK:
            _FETCH_CACHE[cache_key] = (articles, time.time())
        logger.info("News cache: background refresh completed for %r (%d articles)", cache_key[:2] if len(cache_key) > 2 else cache_key, len(articles))
    except Exception as e:
        logger.warning("News cache: background refresh failed for %r: %s", cache_key[:2] if len(cache_key) > 2 else cache_key, e)
    finally:
        _REFRESH_IN_PROGRESS.discard(cache_key)


async def _refresh_pool_background(
    cache_key: tuple[str, ...],
    build_fn: Callable[[], Awaitable[list[NewsArticle]]],
) -> None:
    """Refresh pool in background and update cache."""
    try:
        pool = await build_fn()
        async with _POOL_CACHE_LOCK:
            _POOL_CACHE[cache_key] = (pool, time.time())
        logger.info("News pool: background refresh completed (%d articles)", len(pool))
    except Exception as e:
        logger.warning("News pool: background refresh failed: %s", e)
    finally:
        _POOL_REFRESH_IN_PROGRESS.discard(cache_key)


async def _newsapi_rate_limit() -> None:
    global _NEWSAPI_LIMITER, _NEWSAPI_REQUEST_TIMES
    if _NEWSAPI_LIMITER is None:
        _NEWSAPI_LIMITER = asyncio.Lock()
    async with _NEWSAPI_LIMITER:
        now = time.time()
        _NEWSAPI_REQUEST_TIMES[:] = [t for t in _NEWSAPI_REQUEST_TIMES if now - t < 60]
        while len(_NEWSAPI_REQUEST_TIMES) >= _NEWSAPI_MAX_PER_MINUTE:
            wait = 60 - (now - _NEWSAPI_REQUEST_TIMES[0])
            if wait > 0:
                logger.debug("NewsAPI rate limit: waiting %.1fs", wait)
                await asyncio.sleep(wait)
            _NEWSAPI_REQUEST_TIMES.pop(0)
            now = time.time()
        _NEWSAPI_REQUEST_TIMES.append(time.time())


class NewsProvider(ABC):
    @abstractmethod
    async def fetch(self, query: str, max_articles: int) -> list[NewsArticle]:
        raise NotImplementedError


def _parse_datetime(value: int | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OSError):
            return None
    if isinstance(value, str):
        try:
            dt = parsedate_to_datetime(value)
            return dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            pass
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(value[:19], fmt)
                return dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
    return None


class MockNewsProvider(NewsProvider):
    async def fetch(self, query: str, max_articles: int) -> list[NewsArticle]:
        samples = [
            NewsArticle(
                source="MockWire",
                title="OPEC announces coordinated production cuts",
                description="Major exporters agree on output cuts to support prices.",
                url="https://example.com/opec-cuts",
                published_at=datetime.now(timezone.utc),
                content="OPEC production falls, tightening supply in global crude markets.",
                query_used=query,
            ),
            NewsArticle(
                source="MockWire",
                title="Red Sea disruptions raise shipping insurance costs",
                description="Shipping routes disrupted due to regional conflict.",
                url="https://example.com/red-sea",
                published_at=datetime.now(timezone.utc),
                content="Container route risk increases and freight rates jump.",
                query_used=query,
            ),
            NewsArticle(
                source="MockWire",
                title="China unveils large infrastructure stimulus package",
                description="Fiscal package targets construction and heavy industry.",
                url="https://example.com/china-stimulus",
                published_at=datetime.now(timezone.utc),
                content="Demand expectations rise for steel, copper, and machinery.",
                query_used=query,
            ),
            NewsArticle(
                source="MockWire",
                title="Federal Reserve signals additional rate hikes",
                description="Central bank remains focused on inflation.",
                url="https://example.com/fed-hike",
                published_at=datetime.now(timezone.utc),
                content="Higher rates pressure growth equities and support financial margins.",
                query_used=query,
            ),
            NewsArticle(
                source="MockWire",
                title="NASA and private launch firms accelerate satellite deployment plans",
                description="Launch cadence and satellite infrastructure spending are rising.",
                url="https://example.com/space-launch",
                published_at=datetime.now(timezone.utc),
                content="Orbital launch demand, spacecraft supply chains, and satellite communications investment increase.",
                query_used=query,
            ),
            NewsArticle(
                source="MockWire",
                title="Uranium prices rise as utilities lock in long-term nuclear fuel supply",
                description="Nuclear fuel contracting activity picks up across global utilities.",
                url="https://example.com/uranium",
                published_at=datetime.now(timezone.utc),
                content="Utilities seek uranium, nuclear fuel, and reactor supply security as demand expectations improve.",
                query_used=query,
            ),
            NewsArticle(
                source="MockWire",
                title="Hyperscalers expand data center buildouts to meet AI infrastructure demand",
                description="Power demand and server capacity growth support data center investment.",
                url="https://example.com/data-centers",
                published_at=datetime.now(timezone.utc),
                content="Data center construction, utility load growth, and AI server demand continue to accelerate.",
                query_used=query,
            ),
            NewsArticle(
                source="MockWire",
                title="Rare earth supply concerns intensify after new export controls",
                description="Critical minerals and magnet material markets tighten.",
                url="https://example.com/rare-earths",
                published_at=datetime.now(timezone.utc),
                content="Rare earths, critical minerals, and magnet materials face new supply chain pressure.",
                query_used=query,
            ),
        ]
        query_terms = [term.strip().lower() for term in query.split("OR") if term.strip()]
        ranked = []
        for article in samples:
            text = f"{article.title} {article.description or ''} {article.content or ''}".lower()
            score = sum(1 for term in query_terms if term.lower() in text)
            ranked.append((score, article))
        ranked.sort(key=lambda item: item[0], reverse=True)
        matched = [article for score, article in ranked if score > 0]
        if matched:
            return matched[:max_articles]
        return [article for _, article in ranked[:max_articles]]


class NewsApiProvider(NewsProvider):
    def __init__(self, api_key: str, cache_minutes: int = 180):
        self.api_key = api_key
        self.cache_minutes = cache_minutes

    async def _fetch_impl(self, query: str, max_articles: int) -> list[NewsArticle]:
        await _newsapi_rate_limit()
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": query,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": max_articles,
            "apiKey": self.api_key,
        }
        logger.debug("NewsAPI fetch: query=%r max=%d", query[:60], max_articles)
        payload = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.get(url, params=params)
                    if response.status_code == 429:
                        backoff = 2 ** attempt
                        logger.warning("NewsAPI 429 rate limit, retry in %ds", backoff)
                        await asyncio.sleep(backoff)
                        if attempt < 2:
                            await _newsapi_rate_limit()
                        continue
                    response.raise_for_status()
                    payload = response.json()
                    break
            except httpx.HTTPStatusError:
                raise
            except Exception as e:
                logger.warning("NewsAPI fetch failed: %s", e)
                raise
        if payload is None:
            raise RuntimeError("NewsAPI rate limit exceeded after retries")

        articles: list[NewsArticle] = []
        for item in payload.get("articles", []):
            title = item.get("title") or item.get("description") or ""
            if not title or title == "[Removed]":
                continue
            articles.append(
                NewsArticle(
                    source=(item.get("source") or {}).get("name", "unknown"),
                    title=title,
                    description=item.get("description"),
                    url=item.get("url"),
                    published_at=item.get("publishedAt"),
                    content=item.get("content"),
                    query_used=query,
                )
            )
        return articles

    async def fetch(self, query: str, max_articles: int) -> list[NewsArticle]:
        cache_key = ("newsapi", query, max_articles)
        ttl = self.cache_minutes * 60
        now = time.time()
        async with _FETCH_CACHE_LOCK:
            entry = _FETCH_CACHE.get(cache_key)
            if entry:
                articles, cached_at = entry
                if now - cached_at < ttl:
                    asyncio.create_task(_refresh_fetch_background(
                        cache_key,
                        lambda: self._fetch_impl(query, max_articles),
                    ))
                    logger.info("NewsAPI: cache hit for %r (%d articles, %.1f min old)", query[:50], len(articles), (now - cached_at) / 60)
                    return articles[:max_articles]
        articles = await self._fetch_impl(query, max_articles)
        async with _FETCH_CACHE_LOCK:
            _FETCH_CACHE[cache_key] = (articles, time.time())
            cutoff = time.time() - (self.cache_minutes * 60)
            for k in [k for k, (_, t) in _FETCH_CACHE.items() if t < cutoff]:
                del _FETCH_CACHE[k]
        return articles


def _search_duckduckgo_news(query: str, max_results: int) -> list[NewsArticle]:
    """Sync DuckDuckGo news search. Run in thread to avoid blocking. No API key required."""
    try:
        from duckduckgo_search import DDGS

        results = list(
            DDGS().news(
                keywords=query,
                region="us-en",
                timelimit="w",
                max_results=max_results,
            )
        )
        articles: list[NewsArticle] = []
        for r in results:
            title = r.get("title") or r.get("body") or r.get("description") or ""
            if not title or title == "[Removed]":
                continue
            body = r.get("body") or r.get("description") or r.get("snippet")
            articles.append(
                NewsArticle(
                    source=r.get("source", "DuckDuckGo"),
                    title=title,
                    description=body,
                    url=r.get("url") or r.get("link"),
                    published_at=_parse_datetime(r.get("date") or r.get("published")),
                    content=body,
                    query_used=query,
                )
            )
        return articles
    except ImportError:
        logger.debug("duckduckgo-search not installed; run: pip install duckduckgo-search")
        return []
    except Exception as e:
        logger.debug("DuckDuckGo news search failed: %s", e)
        return []


class DuckDuckGoNewsProvider(NewsProvider):
    """DuckDuckGo news search. Free, no API key. Supplements NewsAPI/Finnhub."""

    def __init__(self, cache_minutes: int = 180):
        self.cache_minutes = cache_minutes

    async def fetch(self, query: str, max_articles: int) -> list[NewsArticle]:
        cache_key = ("duckduckgo_news", query, max_articles)
        ttl = self.cache_minutes * 60
        now = time.time()
        async with _FETCH_CACHE_LOCK:
            entry = _FETCH_CACHE.get(cache_key)
            if entry:
                articles, cached_at = entry
                if now - cached_at < ttl:
                    asyncio.create_task(
                        _refresh_fetch_background(
                            cache_key,
                            lambda: self._fetch_impl(query, max_articles),
                        )
                    )
                    logger.info(
                        "DuckDuckGo news: cache hit for %r (%d articles)",
                        query[:50],
                        len(articles),
                    )
                    return articles[:max_articles]
        articles = await self._fetch_impl(query, max_articles)
        async with _FETCH_CACHE_LOCK:
            _FETCH_CACHE[cache_key] = (articles, time.time())
            cutoff = time.time() - (self.cache_minutes * 60)
            for k in [k for k, (_, t) in _FETCH_CACHE.items() if t < cutoff]:
                del _FETCH_CACHE[k]
        return articles[:max_articles]

    async def _fetch_impl(self, query: str, max_articles: int) -> list[NewsArticle]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, _search_duckduckgo_news, query, max_articles
        )


def _fetch_google_news_rss(query: str, max_results: int) -> list[NewsArticle]:
    """Fetch Google News RSS. Sync, run in executor. No API key required."""
    url = (
        "https://news.google.com/rss/search"
        f"?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"
    )
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
            root = ET.fromstring(resp.text)
    except Exception as e:
        logger.debug("Google News RSS fetch failed: %s", e)
        return []

    articles: list[NewsArticle] = []
    for item in root.iter("item"):
        _add_rss_item(item, query, articles)
    if not articles:
        for item in root.iter("{http://purl.org/rss/1.0/}item"):
            _add_rss_item(item, query, articles)
    if not articles:
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            _add_atom_entry(entry, query, articles)

    return articles[:max_results]


def _add_rss_item(item: ET.Element, query: str, articles: list[NewsArticle]) -> None:
    def _text(tag: str) -> str | None:
        el = item.find(tag)
        if el is None:
            for child in item:
                if child.tag and (child.tag == tag or child.tag.endswith("}" + tag)):
                    t = (child.text or "").strip()
                    return t or None
        if el is not None:
            t = (el.text or "").strip()
            return t or None
        return None

    title = _text("title")
    if not title or title == "[Removed]":
        return
    link = _text("link")
    source = "Google News"
    source_el = item.find("source")
    if source_el is not None:
        if source_el.text:
            source = source_el.text
        elif source_el.get("url"):
            source = source_el.get("url", "Google News")
    articles.append(
        NewsArticle(
            source=source,
            title=title,
            description=_text("description"),
            url=link,
            published_at=_parse_datetime(_text("pubDate")),
            content=_text("description"),
            query_used=query,
        )
    )


def _add_atom_entry(entry: ET.Element, query: str, articles: list[NewsArticle]) -> None:
    """Parse Atom entry (Google News may use Atom format)."""
    ns = "{http://www.w3.org/2005/Atom}"
    title_el = entry.find(f"{ns}title")
    title = (title_el.text or "").strip() if title_el is not None else ""
    if not title or title == "[Removed]":
        return
    link = None
    for link_el in entry.findall(f"{ns}link"):
        link = link_el.get("href")
        if link:
            break
    source = "Google News"
    source_el = entry.find(f"{ns}source")
    if source_el is not None:
        title_el = source_el.find(f"{ns}title")
        if title_el is not None and title_el.text:
            source = title_el.text
    pub = entry.find(f"{ns}published") or entry.find(f"{ns}updated")
    pub_date = (pub.text or "").strip() if pub is not None else None
    summary_el = entry.find(f"{ns}summary") or entry.find(f"{ns}content")
    description = (summary_el.text or "").strip() or None if summary_el is not None else None
    articles.append(
        NewsArticle(
            source=source,
            title=title,
            description=description,
            url=link,
            published_at=_parse_datetime(pub_date),
            content=description,
            query_used=query,
        )
    )


class GoogleNewsRssProvider(NewsProvider):
    """Google News RSS search. Primary news source. Free, no API key. Aggregates many publishers."""

    def __init__(self, cache_minutes: int = 180):
        self.cache_minutes = cache_minutes

    async def fetch(self, query: str, max_articles: int) -> list[NewsArticle]:
        cache_key = ("google_news_rss", query, max_articles)
        ttl = self.cache_minutes * 60
        now = time.time()
        async with _FETCH_CACHE_LOCK:
            entry = _FETCH_CACHE.get(cache_key)
            if entry:
                articles, cached_at = entry
                if now - cached_at < ttl:
                    asyncio.create_task(
                        _refresh_fetch_background(
                            cache_key,
                            lambda: self._fetch_impl(query, max_articles),
                        )
                    )
                    logger.info(
                        "Google News RSS: cache hit for %r (%d articles)",
                        query[:50],
                        len(articles),
                    )
                    return articles[:max_articles]
        articles = await self._fetch_impl(query, max_articles)
        async with _FETCH_CACHE_LOCK:
            _FETCH_CACHE[cache_key] = (articles, time.time())
            cutoff = time.time() - (self.cache_minutes * 60)
            for k in [k for k, (_, t) in _FETCH_CACHE.items() if t < cutoff]:
                del _FETCH_CACHE[k]
        return articles[:max_articles]

    async def _fetch_impl(self, query: str, max_articles: int) -> list[NewsArticle]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, _fetch_google_news_rss, query, max_articles
        )


class FinnhubNewsProvider(NewsProvider):
    """Finnhub market news - free tier, no query param; returns general/crypto news.

    Finnhub ignores the query — the feed is the same every call.
    Uses shared 3hr cache; on cache hit returns immediately and refreshes in background.
    """

    def __init__(self, api_key: str, cache_minutes: int = 180):
        self.api_key = api_key
        self.cache_minutes = cache_minutes

    async def fetch(self, query: str, max_articles: int) -> list[NewsArticle]:
        cache_key = ("finnhub",)  # query ignored
        ttl = self.cache_minutes * 60
        now = time.time()
        async with _FETCH_CACHE_LOCK:
            entry = _FETCH_CACHE.get(cache_key)
            if entry:
                articles, cached_at = entry
                if now - cached_at < ttl:
                    asyncio.create_task(_refresh_fetch_background(
                        cache_key,
                        self._fetch_all,
                    ))
                    logger.info("Finnhub: cache hit (%d articles, %.1f min old)", len(articles), (now - cached_at) / 60)
                    return articles[:max_articles]
        articles = await self._fetch_all()
        async with _FETCH_CACHE_LOCK:
            _FETCH_CACHE[cache_key] = (articles, time.time())
            cutoff = time.time() - (self.cache_minutes * 60)
            for k in [k for k, (_, t) in _FETCH_CACHE.items() if t < cutoff]:
                del _FETCH_CACHE[k]
        return articles[:max_articles]

    async def _fetch_all(self) -> list[NewsArticle]:
        articles: list[NewsArticle] = []
        for category in ("general", "crypto"):
            url = "https://finnhub.io/api/v1/news"
            params = {"category": category, "token": self.api_key}
            try:
                logger.debug("Finnhub fetch: category=%s", category)
                async with httpx.AsyncClient(timeout=12) as client:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    items = response.json() or []
            except Exception as e:
                logger.warning("Finnhub fetch failed for %s: %s", category, e)
                continue
            for item in items:
                headline = item.get("headline") or item.get("summary") or ""
                if not headline or headline == "[Removed]":
                    continue
                articles.append(
                    NewsArticle(
                        source=item.get("source", "Finnhub"),
                        title=headline,
                        description=item.get("summary"),
                        url=item.get("url"),
                        published_at=_parse_datetime(item.get("datetime")),
                        content=item.get("summary"),
                        query_used="",
                    )
                )
        return articles


class AggregatingNewsProvider(NewsProvider):
    """Fetches from multiple providers, deduplicates by URL, merges up to max_articles.
    Google News is primary: fetched first and gets larger allocation."""
    def __init__(self, providers: list[NewsProvider]):
        self.providers = providers

    def _allocation(self, provider: NewsProvider, base: int) -> int:
        """Google News gets 2x allocation as primary source."""
        if isinstance(provider, GoogleNewsRssProvider):
            return min(base * 2, 80)
        return base

    async def fetch(self, query: str, max_articles: int) -> list[NewsArticle]:
        seen_urls: set[str] = set()
        merged: list[NewsArticle] = []
        base = max(3, (max_articles + len(self.providers) - 1) // len(self.providers))
        for provider in self.providers:
            try:
                n = self._allocation(provider, base)
                batch = await provider.fetch(query, n)
                for a in batch:
                    url = (a.url or "").strip()
                    key = url or a.title
                    if key and key not in seen_urls:
                        seen_urls.add(key)
                        merged.append(a)
                        if len(merged) >= max_articles:
                            return merged
            except Exception as e:
                logger.warning("News provider %s failed: %s", type(provider).__name__, e)
                continue
        return merged[:max_articles]


# Module-level cache for PooledNewsProvider: (cache_key -> (articles, timestamp))
# 3hr TTL; on cache hit returns immediately and refreshes in background.
_POOL_CACHE: dict[tuple[str, ...], tuple[list[NewsArticle], float]] = {}
_POOL_CACHE_LOCK = asyncio.Lock()
_POOL_REFRESH_IN_PROGRESS: set[tuple[str, ...]] = set()


class PooledNewsProvider(NewsProvider):
    """Fetches a broad pool of articles once, then filters per-sector on each fetch() call.

    Instead of N separate API calls for N sectors, makes 1 NewsAPI call (broad query)
    + 1 Finnhub fetch (cached), pools the articles, and distributes them to sectors by
    keyword matching. Uses 3hr cache; on cache hit returns immediately and refreshes in background.
    """

    def __init__(self, providers: list[NewsProvider], sector_keys: list[str], cache_minutes: int = 180):
        self.providers = providers
        self.sector_keys = sector_keys
        self.cache_minutes = cache_minutes
        self._pool: list[NewsArticle] | None = None
        self._lock = asyncio.Lock()

    def _cache_key(self) -> tuple[str, ...]:
        return tuple(sorted(self.sector_keys))

    async def _build_pool(self) -> list[NewsArticle]:
        from app.sectors import get_expanded_keywords, get_sector

        # Build a short broad query (NewsAPI max ~500 chars for q param)
        # Use expanded keywords (seeds + synonyms) for better pool coverage
        all_keywords: list[str] = []
        for key in self.sector_keys:
            sector = get_sector(key)
            if sector:
                expanded = get_expanded_keywords(key) or sector.seed_keywords
                all_keywords.extend(expanded[:3])
        unique = list(dict.fromkeys(all_keywords))
        # Trim to stay under NewsAPI's query length limit
        broad_query = ""
        for kw in unique:
            candidate = f"{broad_query} OR {kw}" if broad_query else kw
            if len(candidate) > 450:
                break
            broad_query = candidate

        async def _fetch_one(provider: NewsProvider) -> list[NewsArticle]:
            try:
                if isinstance(provider, GoogleNewsRssProvider):
                    return await provider.fetch(broad_query, 60)
                if isinstance(provider, NewsApiProvider):
                    return await provider.fetch(broad_query, 30)
                return await provider.fetch(broad_query, 40)
            except Exception as e:
                logger.warning("Pool fetch from %s failed: %s", type(provider).__name__, e)
                return []

        batches = await asyncio.gather(*[_fetch_one(p) for p in self.providers])
        seen: set[str] = set()
        pool: list[NewsArticle] = []
        for batch in batches:
            for a in batch:
                key = (a.url or "").strip() or a.title
                if key and key not in seen:
                    seen.add(key)
                    pool.append(a)
        logger.info("News pool: %d unique articles from %d provider(s)", len(pool), len(self.providers))
        return pool

    async def fetch(self, query: str, max_articles: int) -> list[NewsArticle]:
        async with self._lock:
            if self._pool is None:
                cache_key = self._cache_key()
                now = time.time()
                ttl_seconds = self.cache_minutes * 60
                async with _POOL_CACHE_LOCK:
                    entry = _POOL_CACHE.get(cache_key)
                    if entry is not None:
                        pool, cached_at = entry
                        if now - cached_at < ttl_seconds:
                            self._pool = pool
                            logger.info("News pool: cache hit (%d articles, %.1f min old)", len(pool), (now - cached_at) / 60)
                if self._pool is None:
                    self._pool = await self._build_pool()
                    async with _POOL_CACHE_LOCK:
                        _POOL_CACHE[cache_key] = (self._pool, time.time())
                        _POOL_REFRESH_IN_PROGRESS.discard(cache_key)
                        cutoff = time.time() - ttl_seconds
                        for k in [k for k, (_, t) in _POOL_CACHE.items() if t < cutoff]:
                            del _POOL_CACHE[k]

        keywords = [kw.strip().lower() for kw in query.split("OR") if kw.strip()]
        if not keywords:
            return self._pool[:max_articles]

        scored: list[tuple[int, NewsArticle]] = []
        for article in self._pool:
            text = f"{article.title} {article.description or ''} {article.content or ''}".lower()
            hits = sum(1 for kw in keywords if kw in text)
            if hits > 0:
                scored.append((hits, article))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in scored[:max_articles]]
