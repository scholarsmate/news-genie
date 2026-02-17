from __future__ import annotations

import logging

import requests

from newsgenie.config import SETTINGS
from newsgenie.schema import Category, SourceItem
from newsgenie.util.cache import TTLCache
from newsgenie.util.errors import ToolError

log = logging.getLogger(__name__)
_cache = TTLCache(SETTINGS.cache_ttl_seconds)

NEWSAPI_TOP_HEADLINES = "https://newsapi.org/v2/top-headlines"
NEWSAPI_EVERYTHING = "https://newsapi.org/v2/everything"


def _demo_items(category: Category) -> list[SourceItem]:
    demo: dict[str, list[SourceItem]] = {
        "technology": [
            {
                "title": "AI chips keep reshaping data-center spending",
                "url": "https://example.com/tech1",
                "outlet": "DemoWire",
                "published_at": "2026-02-23T12:00:00Z",
                "snippet": "Cloud providers continue to prioritize accelerators and memory bandwidth over general-purpose compute.",
            },
            {
                "title": "New open-source tooling makes LLM apps more testable",
                "url": "https://example.com/tech2",
                "outlet": "DemoTech",
                "published_at": "2026-02-23T10:30:00Z",
                "snippet": "Workflow orchestration frameworks emphasize determinism, retries, and composability for production deployments.",
            },
            {
                "title": "Edge AI adoption accelerates with smaller models",
                "url": "https://example.com/tech3",
                "outlet": "DemoWire",
                "published_at": "2026-02-23T09:15:00Z",
                "snippet": "Quantized models under 3B parameters are being deployed on mobile and IoT devices at scale.",
            },
            {
                "title": "Major cloud provider announces serverless GPU instances",
                "url": "https://example.com/tech4",
                "outlet": "DemoCloud",
                "published_at": "2026-02-23T08:00:00Z",
                "snippet": "Pay-per-inference pricing aims to lower the barrier for startups building AI-first products.",
            },
            {
                "title": "Browser vendors collaborate on new WebGPU standard",
                "url": "https://example.com/tech5",
                "outlet": "DemoTech",
                "published_at": "2026-02-23T07:30:00Z",
                "snippet": "The updated spec enables client-side model inference with near-native performance.",
            },
            {
                "title": "Open-source vector database hits 1.0 milestone",
                "url": "https://example.com/tech6",
                "outlet": "DemoDevOps",
                "published_at": "2026-02-23T06:45:00Z",
                "snippet": "RAG pipelines get a production-ready storage layer with built-in hybrid search.",
            },
        ],
        "finance": [
            {
                "title": "Markets watch inflation prints and rate expectations",
                "url": "https://example.com/fin1",
                "outlet": "DemoFinance",
                "published_at": "2026-02-23T11:15:00Z",
                "snippet": "Bond yields move as traders reprice the path of rate cuts following mixed CPI data.",
            },
            {
                "title": "Earnings week highlights retail and semiconductor sectors",
                "url": "https://example.com/fin2",
                "outlet": "DemoTicker",
                "published_at": "2026-02-23T09:00:00Z",
                "snippet": "Forward guidance dominates sentiment as much as headline EPS beats.",
            },
            {
                "title": "Central banks signal diverging policy paths",
                "url": "https://example.com/fin3",
                "outlet": "DemoFinance",
                "published_at": "2026-02-23T08:30:00Z",
                "snippet": "The ECB hints at further easing while the Fed holds steady, widening yield differentials.",
            },
            {
                "title": "IPO pipeline builds as risk appetite returns",
                "url": "https://example.com/fin4",
                "outlet": "DemoCapital",
                "published_at": "2026-02-23T07:45:00Z",
                "snippet": "Several AI and biotech firms file S-1s, signaling renewed confidence in public markets.",
            },
            {
                "title": "Commodity prices surge on supply-chain disruptions",
                "url": "https://example.com/fin5",
                "outlet": "DemoTicker",
                "published_at": "2026-02-23T07:00:00Z",
                "snippet": "Copper and lithium lead gains as geopolitical tensions and weather events constrain output.",
            },
            {
                "title": "Crypto ETF inflows hit monthly record",
                "url": "https://example.com/fin6",
                "outlet": "DemoCapital",
                "published_at": "2026-02-23T06:15:00Z",
                "snippet": "Institutional allocations drive volume as spot Bitcoin ETFs gain mainstream traction.",
            },
        ],
        "sports": [
            {
                "title": "Playoff races tighten across leagues",
                "url": "https://example.com/s1",
                "outlet": "DemoSports",
                "published_at": "2026-02-23T08:45:00Z",
                "snippet": "Wild card spots and seeding battles heat up heading into the final stretch.",
            },
            {
                "title": "Key injuries could swing the standings",
                "url": "https://example.com/s2",
                "outlet": "DemoArena",
                "published_at": "2026-02-23T07:30:00Z",
                "snippet": "Depth and schedule strength become decisive factors for contending teams.",
            },
            {
                "title": "Trade deadline deals reshape title contenders",
                "url": "https://example.com/s3",
                "outlet": "DemoSports",
                "published_at": "2026-02-23T06:50:00Z",
                "snippet": "Several blockbuster swaps add veteran talent to teams eyeing deep playoff runs.",
            },
            {
                "title": "Rising star breaks scoring records in weekend action",
                "url": "https://example.com/s4",
                "outlet": "DemoArena",
                "published_at": "2026-02-23T06:00:00Z",
                "snippet": "The 22-year-old forward posts a career-high 54-point performance.",
            },
            {
                "title": "International tournament draw sparks global excitement",
                "url": "https://example.com/s5",
                "outlet": "DemoGlobal",
                "published_at": "2026-02-23T05:30:00Z",
                "snippet": "Group-stage matchups pit traditional rivals against each other in the opening round.",
            },
            {
                "title": "Coaches challenge new replay rules in post-game press conferences",
                "url": "https://example.com/s6",
                "outlet": "DemoSports",
                "published_at": "2026-02-23T05:00:00Z",
                "snippet": "Officials defend the expanded use of technology while players call for consistency.",
            },
        ],
        "politics": [
            {
                "title": "Bipartisan group advances landmark oversight bill",
                "url": "https://example.com/pol1",
                "outlet": "DemoPolitics",
                "published_at": "2026-02-23T12:00:00Z",
                "snippet": "The bill would establish new transparency requirements for federal agencies and spending.",
            },
            {
                "title": "Primary season heats up with key state contests",
                "url": "https://example.com/pol2",
                "outlet": "DemoCapitol",
                "published_at": "2026-02-23T11:00:00Z",
                "snippet": "Candidates sharpen messaging as early-voting states set the tone for the cycle.",
            },
            {
                "title": "Supreme Court agrees to hear major regulatory case",
                "url": "https://example.com/pol3",
                "outlet": "DemoPolitics",
                "published_at": "2026-02-23T10:00:00Z",
                "snippet": "The case could reshape the balance of power between Congress and executive agencies.",
            },
            {
                "title": "Diplomatic summit yields new trade framework",
                "url": "https://example.com/pol4",
                "outlet": "DemoWorld",
                "published_at": "2026-02-23T09:00:00Z",
                "snippet": "Negotiators finalize terms aimed at reducing tariffs and harmonizing standards.",
            },
            {
                "title": "State governors push back on federal policy changes",
                "url": "https://example.com/pol5",
                "outlet": "DemoCapitol",
                "published_at": "2026-02-23T08:00:00Z",
                "snippet": "A coalition of governors files legal challenges citing states' rights concerns.",
            },
            {
                "title": "Voter registration drives break midterm records",
                "url": "https://example.com/pol6",
                "outlet": "DemoPolitics",
                "published_at": "2026-02-23T07:00:00Z",
                "snippet": "Grassroots organizations report the highest sign-up rates in over a decade.",
            },
        ],
        "entertainment": [
            {
                "title": "Blockbuster sequel smashes opening-weekend box-office records",
                "url": "https://example.com/ent1",
                "outlet": "DemoScreen",
                "published_at": "2026-02-23T12:00:00Z",
                "snippet": "The highly anticipated sci-fi franchise entry earned $240 million globally in its first three days.",
            },
            {
                "title": "Streaming platform unveils star-studded fall lineup",
                "url": "https://example.com/ent2",
                "outlet": "DemoEntertainment",
                "published_at": "2026-02-23T11:00:00Z",
                "snippet": "A dozen original series and three feature films anchor the service's most ambitious slate yet.",
            },
            {
                "title": "Award-winning director announces surprise indie project",
                "url": "https://example.com/ent3",
                "outlet": "DemoScreen",
                "published_at": "2026-02-23T10:00:00Z",
                "snippet": "The low-budget drama will shoot on location over six weeks with a debut ensemble cast.",
            },
            {
                "title": "Music festival reveals 2026 headliners and expanded stages",
                "url": "https://example.com/ent4",
                "outlet": "DemoBeats",
                "published_at": "2026-02-23T09:00:00Z",
                "snippet": "Organizers add a fourth stage and extend the event to four days for the first time.",
            },
            {
                "title": "Hit TV series renewed for three additional seasons",
                "url": "https://example.com/ent5",
                "outlet": "DemoEntertainment",
                "published_at": "2026-02-23T08:00:00Z",
                "snippet": "The multi-season renewal reflects record viewership and strong international demand.",
            },
            {
                "title": "Video-game adaptation tops charts amid critical acclaim",
                "url": "https://example.com/ent6",
                "outlet": "DemoScreen",
                "published_at": "2026-02-23T07:00:00Z",
                "snippet": "Critics praise the series for balancing faithfulness to the source material with cinematic storytelling.",
            },
        ],
        "general": [
            {
                "title": "Daily briefing: major stories to know today",
                "url": "https://example.com/g1",
                "outlet": "DemoDaily",
                "published_at": "2026-02-23T06:00:00Z",
                "snippet": "A compact roundup of the most important news across categories.",
            },
            {
                "title": "Climate summit reaches landmark agreement on emissions",
                "url": "https://example.com/g2",
                "outlet": "DemoWorld",
                "published_at": "2026-02-23T05:30:00Z",
                "snippet": "Nations commit to accelerated reduction targets with enforceable milestones.",
            },
            {
                "title": "New study reveals global literacy rates continue climbing",
                "url": "https://example.com/g3",
                "outlet": "DemoDaily",
                "published_at": "2026-02-23T05:00:00Z",
                "snippet": "Digital access programs contribute to the fastest decade of improvement on record.",
            },
            {
                "title": "Space agency confirms next crewed mission timeline",
                "url": "https://example.com/g4",
                "outlet": "DemoScience",
                "published_at": "2026-02-23T04:30:00Z",
                "snippet": "The four-person crew will conduct experiments in low-Earth orbit for 30 days.",
            },
            {
                "title": "Major infrastructure bill clears legislative hurdle",
                "url": "https://example.com/g5",
                "outlet": "DemoWorld",
                "published_at": "2026-02-23T04:00:00Z",
                "snippet": "Funding targets bridges, broadband, and clean-energy grid upgrades.",
            },
            {
                "title": "Cultural festival draws record attendance worldwide",
                "url": "https://example.com/g6",
                "outlet": "DemoDaily",
                "published_at": "2026-02-23T03:30:00Z",
                "snippet": "Streaming and in-person events combine to reach an estimated 200 million viewers.",
            },
        ],
    }
    return demo.get(category, demo["general"])


def _fetch_news_live(category: Category, query: str | None, limit: int) -> list[SourceItem]:
    headers = {"X-Api-Key": SETTINGS.news_api_key}
    if query and query.strip():
        params = {"q": query, "language": SETTINGS.news_lang, "pageSize": min(limit, 20), "sortBy": "publishedAt"}
        url = NEWSAPI_EVERYTHING
    else:
        cat = category if category in ("sports", "technology", "general", "politics", "entertainment") else "business"
        params = {"category": cat, "country": SETTINGS.news_country, "pageSize": min(limit, 20)}
        url = NEWSAPI_TOP_HEADLINES
    log.info("NewsAPI  %s  %s  params=%s", "GET", url, params)
    r = requests.get(url, params=params, headers=headers, timeout=12)
    log.info("NewsAPI  status=%d  size=%d bytes", r.status_code, len(r.content))
    r.raise_for_status()
    data = r.json()
    items: list[SourceItem] = []
    for a in data.get("articles", [])[:limit]:
        items.append(
            {
                "title": a.get("title") or "(untitled)",
                "url": a.get("url") or "",
                "outlet": (a.get("source") or {}).get("name") or "Unknown",
                "published_at": a.get("publishedAt") or "",
                "snippet": a.get("description") or "",
            }
        )
    return items


def fetch_news(category: Category, query: str | None = None, limit: int = 8) -> list[SourceItem]:
    if SETTINGS.is_demo() or not SETTINGS.news_api_key:
        log.debug("fetch_news  using demo data  category=%s", category)
        return _demo_items(category)[:limit]
    log.info("fetch_news  category=%s  query=%s  limit=%d", category, query, limit)

    cache_key = f"news:{category}:{query}:{limit}"
    try:
        return _cache.get_or_set(cache_key, lambda: _fetch_news_live(category, query, limit))
    except Exception as e:
        log.warning("News fetch failed: %s", e)
        raise ToolError(f"News tool failed: {e}") from e
