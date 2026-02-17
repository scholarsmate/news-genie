from newsgenie.tools.search import _clean_topic, _demo_search


def test_clean_topic_strips_question_prefix():
    assert _clean_topic("Did Crypto ETF inflows hit monthly record?") == "Crypto ETF inflows hit monthly record"
    assert _clean_topic("Is the housing market crashing?") == "The housing market crashing"
    assert _clean_topic("Has SpaceX launched the new rocket?") == "SpaceX launched the new rocket"


def test_clean_topic_plain_phrase_unchanged():
    assert _clean_topic("latest tech news") == "Latest tech news"


def test_demo_search_titles_use_clean_topic():
    results = _demo_search("Did Crypto ETF inflows hit monthly record?")
    for item in results[:4]:
        assert "Did " not in item["title"], f"Raw query leaked into title: {item['title']}"
        assert "?" not in item["snippet"], f"Question mark leaked into snippet: {item['snippet']}"


def test_demo_search_crypto_bonus():
    results = _demo_search("Did Crypto ETF inflows hit monthly record?")
    outlets = [r["outlet"] for r in results]
    assert "DemoFinance" in outlets


def test_demo_search_finance_bonus():
    results = _demo_search("stock market earnings report")
    titles = [r["title"] for r in results]
    assert any("Financial markets" in t for t in titles)
