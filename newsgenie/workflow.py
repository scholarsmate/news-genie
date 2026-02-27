from __future__ import annotations

import json
import logging
import re
import time
import uuid
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


def _parse_structured_response(raw: str) -> tuple[str, list[str]] | None:
    """Parse a JSON response with shape: {answer_markdown: str, citations: list[str]}."""
    candidates: list[str] = [raw.strip()]
    fenced = re.findall(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", raw, flags=re.IGNORECASE)
    candidates.extend(fenced)

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidates.append(raw[start : end + 1].strip())

    for candidate in candidates:
        if not candidate:
            continue
        try:
            data = json.loads(candidate)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue

        answer = data.get("answer_markdown") or data.get("answer") or ""
        if not isinstance(answer, str):
            answer = str(answer)

        raw_citations = data.get("citations")
        citations = [str(url) for url in raw_citations] if isinstance(raw_citations, list) else []
        return answer.strip(), citations

    return None


def _request_id(state: AgentState) -> str:
    meta = state.setdefault("meta", {})
    rid = meta.get("request_id")
    if isinstance(rid, str) and rid:
        return rid
    rid = uuid.uuid4().hex[:12]
    meta["request_id"] = rid
    return rid


def _mark_timing(state: AgentState, node_name: str, started_at: float) -> None:
    elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
    meta = state.setdefault("meta", {})
    timings = meta.get("timings_ms")
    if not isinstance(timings, dict):
        timings = {}
        meta["timings_ms"] = timings
    timings[node_name] = elapsed_ms
    log.info("request_id=%s node=%s elapsed_ms=%.2f", _request_id(state), node_name, elapsed_ms)


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
    started = time.perf_counter()
    state["errors"] = state.get("errors", [])
    state["warnings"] = state.get("warnings", [])
    state["citations"] = []
    state["news_items"] = []
    state["search_items"] = []
    state["meta"] = state.get("meta", {})
    _request_id(state)
    _mark_timing(state, "ingest", started)
    return state


def node_classify(state: AgentState) -> AgentState:
    started = time.perf_counter()
    decision = classify_intent(state["user_query"], state["category"])
    state["decision"] = decision
    state["intent"] = decision["intent"]
    log.info(
        "request_id=%s intent=%s category=%s entities=%s",
        _request_id(state),
        decision["intent"],
        decision.get("category"),
        decision.get("entities", []),
    )
    _mark_timing(state, "classify", started)
    return state


def node_retrieve(state: AgentState) -> AgentState:
    started = time.perf_counter()
    request_id = _request_id(state)
    intent = state["intent"]
    category = state["category"]
    q = state["user_query"]
    use_news = state.get("use_news", True)
    use_search = state.get("use_search", True)

    if use_news and intent in ("NEWS_CATEGORY", "NEWS_TOPIC", "MIXED", "FACT_CHECK"):
        topic = q if intent in ("NEWS_TOPIC", "FACT_CHECK") else None
        news_limit = state.get("news_limit") or 8
        log.info("request_id=%s fetch_news category=%s topic=%s limit=%d", request_id, category, topic, news_limit)
        try:
            state["news_items"] = rank_sources(_safe_fetch_news(category, topic, limit=news_limit))
            log.info("request_id=%s news_items=%d", request_id, len(state["news_items"]))
        except Exception as e:
            log.warning("request_id=%s news_fetch_error=%s", request_id, e)
            state["errors"].append(str(e))
    elif not use_news and intent in ("NEWS_CATEGORY", "NEWS_TOPIC", "MIXED", "FACT_CHECK"):
        log.info("request_id=%s news_api_disabled=true", request_id)

    if use_search and intent in ("FACT_CHECK", "MIXED"):
        log.info("request_id=%s web_search query=%s", request_id, q)
        try:
            state["search_items"] = rank_sources(web_search(q))
            log.info("request_id=%s search_items=%d", request_id, len(state["search_items"]))
        except Exception as e:
            log.warning("request_id=%s web_search_error=%s", request_id, e)
            state["errors"].append(str(e))
    elif not use_search and intent in ("FACT_CHECK", "MIXED"):
        log.info("request_id=%s web_search_disabled=true", request_id)

    _mark_timing(state, "retrieve", started)
    return state


def node_compose(state: AgentState) -> AgentState:
    started = time.perf_counter()
    request_id = _request_id(state)
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

    structured_output = (
        "Return ONLY valid JSON (no prose, no code fences) with exactly these keys: "
        "answer_markdown (string), citations (array of URLs). "
        "Citations must be URLs from the provided sources that support the answer."
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
            + "\n\nWrite a helpful response with inline citations as markdown links. "
            + "Do NOT add a separate sources section at the end.\n"
            + structured_output
        )
    else:
        prompt = (
            f"User query: {q}\n"
            + history_block
            + "\nAnswer as best you can. If real-time facts are required, state what data is missing.\n"
            + structured_output
        )

    try:
        raw_response = chat(prompt, system=sys)
    except Exception as e:
        state["errors"].append(f"LLM call failed: {e}")
        raw_response = "Sorry, I couldn't generate a response right now. Please try again."
        log.warning("request_id=%s llm_call_failed=%s", request_id, e)

    parsed = _parse_structured_response(raw_response)
    if parsed is not None:
        ans, cited_urls = parsed
        log.info("request_id=%s structured_response=true citations=%d", request_id, len(cited_urls))
    else:
        ans = raw_response
        cited_urls = []
        log.info("request_id=%s structured_response=false", request_id)

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
    url_candidates = cited_urls
    if not url_candidates:
        md_links = re.findall(r"\[[^\]]+\]\((https?://[^\s)]+)\)", ans)
        if md_links:
            url_candidates = md_links
        else:
            bare = re.findall(r"https?://\S+", ans)
            url_candidates = [u.rstrip(").,]") for u in bare]

    seen: set[str] = set()
    enriched: list[str] = []
    for url in url_candidates:
        norm = _normalize_url(url)
        if norm in seen:
            continue
        seen.add(norm)
        meta = _url_meta.get(norm)
        if meta:
            label = f"{meta['outlet']} — {meta['title']}"
            suffix = " (memory)" if norm in memory_urls else ""
            enriched.append(f"[{label}]({url}){suffix}")
        else:
            enriched.append(f"[{url}]({url})")

    state["citations"] = enriched
    state["answer"] = ans
    if state["intent"] != "GENERAL_QA" and not state["citations"] and sources:
        state["warnings"].append("No citations detected; consider enforcing stricter citation checks.")
    _mark_timing(state, "compose", started)
    return state


def node_finalize(state: AgentState) -> AgentState:
    started = time.perf_counter()
    footer: list[str] = []
    if state.get("warnings"):
        footer.append("Warnings: " + "; ".join(state["warnings"]))
    if state.get("errors"):
        footer.append("Errors: " + "; ".join(state["errors"]))
    if footer:
        state["answer"] = state.get("answer", "") + "\n\n---\n" + "\n".join(footer)
    _mark_timing(state, "finalize", started)
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
