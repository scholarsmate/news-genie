from newsgenie.tools.trust import domain_of, rank_sources, trust_score


def test_trust_score_bounds():
    item = {"title": "t", "url": "https://reuters.com/a", "outlet": "Reuters", "published_at": "", "snippet": "s"}
    s = trust_score(item)  # type: ignore
    assert 0.0 <= s <= 1.0


def test_high_reputation_boosts_score():
    high = {"title": "t", "url": "https://reuters.com/a", "outlet": "Reuters", "published_at": "", "snippet": "s"}
    low = {"title": "t", "url": "https://randomblog.xyz/a", "outlet": "Random", "published_at": "", "snippet": "s"}
    assert trust_score(high) > trust_score(low)  # type: ignore


def test_domain_of_strips_www():
    assert domain_of("https://www.reuters.com/article") == "reuters.com"
    assert domain_of("https://reuters.com/article") == "reuters.com"


def test_rank_sources_sorts_descending():
    items = [
        {"title": "t", "url": "https://randomblog.xyz/a", "outlet": "R", "published_at": "", "snippet": "s"},
        {"title": "t", "url": "https://reuters.com/a", "outlet": "Reuters", "published_at": "", "snippet": "s"},
    ]
    ranked = rank_sources(items)  # type: ignore
    assert ranked[0]["url"] == "https://reuters.com/a"
    assert ranked[0]["score"] >= ranked[1]["score"]
