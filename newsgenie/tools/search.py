from __future__ import annotations

import logging
import re

import requests

from newsgenie.config import SETTINGS
from newsgenie.schema import SourceItem
from newsgenie.util.cache import TTLCache
from newsgenie.util.errors import ToolError

log = logging.getLogger(__name__)
_cache = TTLCache(SETTINGS.cache_ttl_seconds)

_QUESTION_PREFIX = re.compile(
    r"^(did|do|does|is|are|was|were|has|have|had|can|could|will|would|should)\s+",
    re.IGNORECASE,
)


def _clean_topic(query: str) -> str:
    """Strip question syntax to produce a short noun-phrase topic label."""
    topic = _QUESTION_PREFIX.sub("", query)
    topic = topic.rstrip("?!. ").strip()
    # Capitalise first letter
    return topic[:1].upper() + topic[1:] if topic else query


def _demo_search(query: str) -> list[SourceItem]:
    q_lower = query.lower()
    topic = _clean_topic(query)
    results: list[SourceItem] = [
        {
            "title": f"Overview: {topic}",
            "url": "https://example.com/overview",
            "outlet": "DemoEncyclopedia",
            "published_at": "2026-02-23T12:00:00Z",
            "snippet": f"A comprehensive overview of {topic}, covering key definitions, history, and current relevance.",
        },
        {
            "title": f"Expert analysis: {topic}",
            "url": "https://example.com/analysis",
            "outlet": "DemoResearch",
            "published_at": "2026-02-23T11:30:00Z",
            "snippet": f"Researchers have examined {topic} from multiple angles, noting both consensus views and ongoing debates.",
        },
        {
            "title": f"Fact-check: claims about {topic}",
            "url": "https://example.com/factcheck",
            "outlet": "DemoVerify",
            "published_at": "2026-02-23T11:00:00Z",
            "snippet": f"Common claims related to {topic} are rated against primary sources and peer-reviewed evidence.",
        },
        {
            "title": f"Recent developments in {topic}",
            "url": "https://example.com/recent",
            "outlet": "DemoNews",
            "published_at": "2026-02-23T10:30:00Z",
            "snippet": f"The latest updates on {topic} include policy changes, new studies, and industry reactions.",
        },
    ]
    # Add topic-aware bonus results
    if any(w in q_lower for w in ("ai", "artificial intelligence", "machine learning", "llm")):
        results.append(
            {
                "title": "State of AI report 2026",
                "url": "https://example.com/ai-report",
                "outlet": "DemoResearch",
                "published_at": "2026-02-23T09:00:00Z",
                "snippet": "Annual survey of AI capabilities, adoption, safety research, and regulatory trends.",
            }
        )
    if any(w in q_lower for w in ("climate", "environment", "emissions", "warming")):
        results.append(
            {
                "title": "Global climate data tracker",
                "url": "https://example.com/climate-data",
                "outlet": "DemoScience",
                "published_at": "2026-02-23T09:00:00Z",
                "snippet": "Real-time dashboards for temperature anomalies, CO₂ levels, and renewable energy adoption.",
            }
        )
    if any(w in q_lower for w in ("health", "medical", "vaccine", "disease")):
        results.append(
            {
                "title": "Public health evidence repository",
                "url": "https://example.com/health-evidence",
                "outlet": "DemoMedical",
                "published_at": "2026-02-23T09:00:00Z",
                "snippet": "Curated collection of clinical trial results, meta-analyses, and WHO guidance documents.",
            }
        )
    if any(w in q_lower for w in ("crypto", "bitcoin", "etf", "ethereum", "blockchain")):
        results.append(
            {
                "title": "Crypto ETF tracker: flows and holdings",
                "url": "https://example.com/crypto-etf",
                "outlet": "DemoFinance",
                "published_at": "2026-02-23T09:00:00Z",
                "snippet": "Daily net-flow data for spot Bitcoin and Ether ETFs with AUM breakdowns by issuer.",
            }
        )
    if any(
        w in q_lower
        for w in (
            "stock",
            "market",
            "earnings",
            "ipo",
            "bonds",
            "yields",
            "inflation",
            "rate",
            "fed",
            "ecb",
            "commodity",
            "finance",
        )
    ):
        results.append(
            {
                "title": "Financial markets dashboard",
                "url": "https://example.com/markets",
                "outlet": "DemoFinance",
                "published_at": "2026-02-23T09:00:00Z",
                "snippet": "Live indices, sector heatmaps, and earnings calendars for global equity and fixed-income markets.",
            }
        )
    return results


def _search_live(query: str, limit: int) -> list[SourceItem]:
    headers: dict[str, str | None] = {
        # Brave uses X-Subscription-Token; other APIs may use X-Api-Key
        "X-Subscription-Token": SETTINGS.search_api_key,
        "Accept": "application/json",
    }
    params: dict = {"q": query, "count": limit}
    log.info("Brave Search  GET %s  params=%s", SETTINGS.search_api_base_url, params)
    r = requests.get(SETTINGS.search_api_base_url, params=params, headers=headers, timeout=12)  # type: ignore[arg-type]
    log.info("Brave Search  status=%d  size=%d bytes", r.status_code, len(r.content))
    r.raise_for_status()
    data = r.json()
    # Brave nests results under "web.results"; fall back for other providers
    raw = (data.get("web") or {}).get("results") or data.get("results") or data.get("items") or []
    items: list[SourceItem] = []
    for it in raw[:limit]:
        items.append(
            {
                "title": it.get("title") or "(untitled)",
                "url": it.get("url") or it.get("link") or "",
                "outlet": it.get("source") or it.get("displayLink") or "Search",
                "published_at": it.get("published_at") or it.get("age") or "",
                "snippet": it.get("snippet") or it.get("description") or "",
            }
        )
    return items


def web_search(query: str, limit: int = 5) -> list[SourceItem]:
    if SETTINGS.is_demo() or not (SETTINGS.search_api_key and SETTINGS.search_api_base_url):
        log.debug("web_search  using demo data  query=%s", query)
        return _demo_search(query)[:limit]
    log.info("web_search  query=%s  limit=%d", query, limit)

    cache_key = f"search:{query}:{limit}"
    try:
        return _cache.get_or_set(cache_key, lambda: _search_live(query, limit))
    except Exception as e:
        log.warning("Web search failed: %s", e)
        raise ToolError(f"Search tool failed: {e}") from e
