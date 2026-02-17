from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from langgraph.graph import END, StateGraph  # type: ignore[import-untyped]
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from newsgenie.llm import chat
from newsgenie.schema import AgentState, Category, IntentDecision, SourceItem
from newsgenie.tools.news import fetch_news
from newsgenie.tools.search import web_search
from newsgenie.tools.trust import rank_sources

log = logging.getLogger(__name__)


def _normalize_url(url: str) -> str:
    """Normalize a URL for comparison (strip scheme differences, trailing slashes, www.)."""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parsed.path.rstrip("/")
    return f"{host}{path}{'?' + parsed.query if parsed.query else ''}"


@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=6))
def _safe_fetch_news(category: Category, query: str | None, limit: int = 8) -> list[SourceItem]:
    return fetch_news(category=category, query=query, limit=limit)


def classify_intent(query: str, category: Category) -> IntentDecision:
    q = query.lower().strip()
    news_words = (
        "headline",
        "headlines",
        "news",
        "latest",
        "update",
        "updates",
        "today",
        "breaking",
        "report",
        "reports",
        "stories",
        "briefing",
        "roundup",
        "what happened",
        "what's new",
        "whats new",
        "current events",
    )
    fact_words = (
        "is it true",
        "fact check",
        "verify",
        "debunk",
        "hoax",
        "is this real",
        "really true",
        "actually true",
        "confirm",
    )
    # "Did X happen?" style questions are verification/fact-check
    fact_prefixes = ("did ", "has ", "have ", "was ", "were ", "is ", "are ")

    if any(w in q for w in fact_words):
        return {"intent": "FACT_CHECK", "category": category, "entities": [], "timeframe": "recent"}

    # Yes/no questions that start with a verb are usually asking to verify a claim
    if any(q.startswith(p) for p in fact_prefixes) and q.endswith("?"):
        return {"intent": "FACT_CHECK", "category": category, "entities": [], "timeframe": "recent"}

    if any(w in q for w in news_words):
        entities = [tok for tok in query.split() if tok[:1].isupper() and tok[1:].isalpha() and len(tok) > 2]
        if entities:
            return {"intent": "NEWS_TOPIC", "category": category, "entities": entities, "timeframe": "today"}
        return {"intent": "NEWS_CATEGORY", "category": category, "entities": [], "timeframe": "today"}

    return {"intent": "GENERAL_QA", "category": category, "entities": []}


def node_ingest(state: AgentState) -> AgentState:
    state["errors"] = state.get("errors", [])
    state["warnings"] = state.get("warnings", [])
    state["citations"] = []
    state["news_items"] = []
    state["search_items"] = []
    state["meta"] = state.get("meta", {})
    return state


def node_classify(state: AgentState) -> AgentState:
    decision = classify_intent(state["user_query"], state["category"])
    state["decision"] = decision
    state["intent"] = decision["intent"]
    log.info(
        "Classified intent=%s  category=%s  entities=%s",
        decision["intent"],
        decision.get("category"),
        decision.get("entities", []),
    )
    return state


def node_retrieve(state: AgentState) -> AgentState:
    intent = state["intent"]
    category = state["category"]
    q = state["user_query"]
    use_news = state.get("use_news", True)
    use_search = state.get("use_search", True)

    if use_news and intent in ("NEWS_CATEGORY", "NEWS_TOPIC", "MIXED", "FACT_CHECK"):
        topic = q if intent in ("NEWS_TOPIC", "FACT_CHECK") else None
        news_limit = state.get("news_limit") or 8
        log.info("Fetching news  category=%s  topic=%s  limit=%d", category, topic, news_limit)
        try:
            state["news_items"] = rank_sources(_safe_fetch_news(category, topic, limit=news_limit))
            log.info("News returned %d items", len(state["news_items"]))
        except Exception as e:
            log.warning("News fetch error: %s", e)
            state["errors"].append(str(e))
    elif not use_news and intent in ("NEWS_CATEGORY", "NEWS_TOPIC", "MIXED", "FACT_CHECK"):
        log.info("News API disabled by user — skipping")

    if use_search and intent in ("FACT_CHECK", "MIXED"):
        log.info("Running web search  query=%s", q)
        try:
            state["search_items"] = rank_sources(web_search(q))
            log.info("Web search returned %d items", len(state["search_items"]))
        except Exception as e:
            log.warning("Web search error: %s", e)
            state["errors"].append(str(e))
    elif not use_search and intent in ("FACT_CHECK", "MIXED"):
        log.info("Web Search disabled by user — skipping")

    return state


def node_compose(state: AgentState) -> AgentState:
    q = state["user_query"]
    news_items = state.get("news_items") or []
    search_items = state.get("search_items") or []
    memory_items = state.get("category_news_memory") or []

    sources: list[str] = []
    for it in news_items:
        sources.append(f"[NEWS] {it['outlet']} | {it['title']} | {it['url']} | {it.get('snippet', '')}")
    for it in search_items:
        sources.append(f"[WEB] {it['outlet']} | {it['title']} | {it['url']} | {it.get('snippet', '')}")

    # Include remembered headlines for this category as background context
    # Only add memory items that aren't already in the live sources
    live_urls = {_normalize_url(it["url"]) for it in news_items}
    for it in memory_items:
        if _normalize_url(it["url"]) not in live_urls:
            sources.append(f"[MEMORY] {it['outlet']} | {it['title']} | {it['url']} | {it.get('snippet', '')}")

    sys = (
        "You are NewsGenie. If sources are provided, ground your response in them. "
        "Cite sources inline as markdown links, e.g. [Outlet](url), woven naturally into the text. "
        "Do not invent facts. If evidence is missing or conflicting, say so. "
        "You may also use prior conversation context when answering follow-up questions. "
        "Do NOT add a separate 'Sources' or 'Cited sources' section at the end — citations must be inline only."
    )

    # Build conversation context from recent history (last few turns)
    history = state.get("chat_history") or []
    history_block = ""
    if history:
        history_lines: list[str] = []
        for msg in history[-6:]:  # last 3 exchanges (6 messages)
            role = msg.get("role", "user").capitalize()
            content = msg.get("content", "")
            # Truncate long assistant answers to keep prompt compact
            if role == "Assistant" and len(content) > 400:
                content = content[:400] + "…"
            history_lines.append(f"{role}: {content}")
        history_block = "\n\nRecent conversation:\n" + "\n".join(history_lines) + "\n"

    if sources:
        prompt = (
            f"User query: {q}\n"
            + history_block
            + "\nSources (use these; do not invent new facts):\n"
            + "\n".join(sources)
            + "\n\nWrite a helpful response with inline citations as markdown links. Do NOT add a separate sources section at the end."
        )
    else:
        prompt = (
            f"User query: {q}\n"
            + history_block
            + "\nAnswer as best you can. If real-time facts are required, state what data is missing."
        )

    try:
        ans = chat(prompt, system=sys)
    except Exception as e:
        state["errors"].append(f"LLM call failed: {e}")
        ans = "Sorry, I couldn't generate a response right now. Please try again."

    # Strip any trailing "Cited sources" / "Sources" block the LLM might still add
    ans = re.sub(
        r"\n+(?:\*{0,2})(?:Cited )?[Ss]ources:?(?:\*{0,2})\s*\n(?:[-•*]\s*.+\n?)+\s*$",
        "",
        ans,
    ).rstrip()

    # Build a URL→metadata lookup from all source items fed to the prompt
    _url_meta: dict[str, dict[str, str]] = {}
    for it in news_items:
        _url_meta[_normalize_url(it["url"])] = {"outlet": it["outlet"], "title": it["title"], "kind": "NEWS", "url": it["url"]}
    for it in search_items:
        _url_meta[_normalize_url(it["url"])] = {"outlet": it["outlet"], "title": it["title"], "kind": "WEB", "url": it["url"]}
    memory_urls: set[str] = set()
    for it in memory_items:
        norm = _normalize_url(it["url"])
        memory_urls.add(norm)
        if norm not in _url_meta:
            _url_meta[norm] = {"outlet": it["outlet"], "title": it["title"], "kind": "MEMORY", "url": it["url"]}

    # Extract all URLs from the answer (markdown links or bare)
    md_links = re.findall(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", ans)
    if not md_links:
        bare = re.findall(r"https?://\S+", ans)
        md_links = [("", u.rstrip(").,]")) for u in bare]

    seen: set[str] = set()
    enriched: list[str] = []
    for _link_text, url in md_links:
        norm = _normalize_url(url)
        if norm in seen:
            continue
        seen.add(norm)
        meta = _url_meta.get(norm)
        if meta:
            label = f"{meta['outlet']} — {meta['title']}"
            tag = ' <span title="Recalled from earlier headlines">🧠</span>' if norm in memory_urls else ""
            enriched.append(f"[{label}]({url}){tag}")
        else:
            enriched.append(f"[{_link_text or url}]({url})")

    state["citations"] = enriched
    state["answer"] = ans
    if state["intent"] != "GENERAL_QA" and not state["citations"] and sources:
        state["warnings"].append("No citations detected; consider enforcing stricter citation checks.")
    return state


def node_finalize(state: AgentState) -> AgentState:
    footer: list[str] = []
    if state.get("warnings"):
        footer.append("Warnings: " + "; ".join(state["warnings"]))
    if state.get("errors"):
        footer.append("Errors: " + "; ".join(state["errors"]))
    if footer:
        state["answer"] = state.get("answer", "") + "\n\n---\n" + "\n".join(footer)
    return state


def build_graph() -> Any:
    g = StateGraph(AgentState)

    g.add_node("ingest", node_ingest)  # type: ignore[reportUnknownMemberType]
    g.add_node("classify", node_classify)  # type: ignore[reportUnknownMemberType]
    g.add_node("retrieve", node_retrieve)  # type: ignore[reportUnknownMemberType]
    g.add_node("compose", node_compose)  # type: ignore[reportUnknownMemberType]
    g.add_node("finalize", node_finalize)  # type: ignore[reportUnknownMemberType]

    g.set_entry_point("ingest")
    g.add_edge("ingest", "classify")
    g.add_edge("classify", "retrieve")
    g.add_edge("retrieve", "compose")
    g.add_edge("compose", "finalize")
    g.add_edge("finalize", END)

    return g.compile()  # type: ignore[reportUnknownMemberType]
