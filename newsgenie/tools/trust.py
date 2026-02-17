from __future__ import annotations

from urllib.parse import urlparse

from newsgenie.schema import SourceItem

HIGH_REPUTATION_DOMAINS = {
    "reuters.com",
    "apnews.com",
    "bbc.co.uk",
    "bbc.com",
    "wsj.com",
    "ft.com",
    "economist.com",
    "nytimes.com",
    "theverge.com",
    "arstechnica.com",
    "espn.com",
    "nba.com",
    "nhl.com",
}


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def trust_score(item: SourceItem) -> float:
    d = domain_of(item["url"])
    base = 0.5
    if d in HIGH_REPUTATION_DOMAINS:
        base += 0.3
    if item.get("snippet"):
        base += 0.1
    if item.get("title"):
        base += 0.1
    return min(base, 1.0)


def rank_sources(items: list[SourceItem]) -> list[SourceItem]:
    scored: list[SourceItem] = []
    for it in items:
        it2 = dict(it)
        it2["score"] = trust_score(it)
        scored.append(it2)  # type: ignore
    scored.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return scored
