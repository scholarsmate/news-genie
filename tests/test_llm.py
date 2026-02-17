from newsgenie.llm import _demo_answer


def test_demo_answer_general_qa():
    """No sources → general Q&A demo response mentioning the query."""
    result = _demo_answer("User query: How does TCP work?\n\nAnswer as best you can.")
    assert "demo" in result.lower()
    assert "TCP" in result


def test_demo_answer_with_sources():
    """When sources are in the prompt, demo answer summarises them with citations."""
    prompt = (
        "User query: latest tech news\n\n"
        "Sources (use these; do not invent new facts):\n"
        "[NEWS] DemoWire | AI chips reshape spending | https://example.com/tech1 | Cloud providers prioritize accelerators.\n"
        "[WEB] DemoSearch | Overview: tech | https://example.com/overview | A comprehensive overview.\n"
    )
    result = _demo_answer(prompt)
    assert "AI chips" in result
    assert "https://example.com/tech1" in result
    assert "demo" in result.lower()


def test_demo_answer_no_query_match():
    """Handles prompts that don't contain a 'User query:' prefix gracefully."""
    result = _demo_answer("Tell me about quantum computing")
    assert "demo" in result.lower()
