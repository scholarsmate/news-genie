from newsgenie.workflow import classify_intent


def test_classify_general():
    d = classify_intent("Explain zero-knowledge proofs", "general")
    assert d["intent"] == "GENERAL_QA"


def test_classify_general_with_nongeneral_category():
    """A plain Q&A should stay GENERAL_QA even when the sidebar category is tech/finance/sports."""
    for cat in ("technology", "finance", "sports"):
        d = classify_intent("How does TCP work?", cat)
        assert d["intent"] == "GENERAL_QA", f"Expected GENERAL_QA for category={cat}, got {d['intent']}"


def test_classify_news():
    d = classify_intent("Give me tech headlines today", "technology")
    assert d["intent"] in ("NEWS_CATEGORY", "NEWS_TOPIC")


def test_classify_news_keyword_variant():
    d = classify_intent("latest updates on AI", "general")
    assert d["intent"] in ("NEWS_CATEGORY", "NEWS_TOPIC")


def test_classify_fact_check():
    d = classify_intent("Fact check: is the moon made of cheese?", "general")
    assert d["intent"] == "FACT_CHECK"


def test_classify_fact_check_verify():
    d = classify_intent("Can you verify this claim about vaccines?", "general")
    assert d["intent"] == "FACT_CHECK"


def test_classify_entities_extracted():
    d = classify_intent("News about Tesla and Apple", "technology")
    assert d["intent"] == "NEWS_TOPIC"
    assert "Tesla" in d.get("entities", [])
    assert "Apple" in d.get("entities", [])


def test_classify_did_question_as_fact_check():
    """Yes/no questions starting with Did/Has/Is/Was + '?' are fact-checks."""
    d = classify_intent("Did Crypto ETF inflows hit monthly record?", "finance")
    assert d["intent"] == "FACT_CHECK"


def test_classify_is_question_as_fact_check():
    d = classify_intent("Is the housing market crashing?", "finance")
    assert d["intent"] == "FACT_CHECK"


def test_classify_has_question_as_fact_check():
    d = classify_intent("Has SpaceX launched the new rocket?", "technology")
    assert d["intent"] == "FACT_CHECK"


def test_classify_whats_new():
    d = classify_intent("What's new in tech?", "technology")
    assert d["intent"] in ("NEWS_CATEGORY", "NEWS_TOPIC")


def test_classify_breaking():
    d = classify_intent("Any breaking stories?", "general")
    assert d["intent"] in ("NEWS_CATEGORY", "NEWS_TOPIC")


def test_classify_verb_question_without_mark_stays_qa():
    """Verb-prefix questions without '?' should NOT auto-classify as fact-check."""
    d = classify_intent("Did you know TCP was invented in the 1970s", "general")
    assert d["intent"] == "GENERAL_QA"
