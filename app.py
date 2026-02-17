from __future__ import annotations

import logging
from typing import Any, Protocol, cast

import streamlit as st

from newsgenie import __version__
from newsgenie.config import SETTINGS
from newsgenie.workflow import build_graph

# ── Initialise logging (once) ──
logging.basicConfig(
    level=getattr(logging, SETTINGS.log_level.upper(), logging.INFO),
    format="%(asctime)s  %(levelname)-5s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


class InvokableGraph(Protocol):
    def invoke(self, input: dict[str, Any], *args: Any, **kwargs: Any) -> dict[str, Any]: ...


@st.cache_resource
def _cached_graph() -> InvokableGraph:
    return cast(InvokableGraph, build_graph())


st.set_page_config(page_title="NewsGenie", page_icon="🧞‍♂️", layout="wide")
st.title("🧞‍♂️ NewsGenie")
st.caption(
    f"v{__version__} · Unified news + Q&A assistant · "
    "[GitHub](https://github.com/scholarsmate/news-genie)"
)

if SETTINGS.is_demo():
    st.info("Running in DEMO MODE (no API keys detected). Add keys in .env to enable live tools.")

_CATEGORY_ICONS: dict[str, str] = {
    "general": "🌍",
    "entertainment": "🎬",
    "finance": "💹",
    "politics": "🏛️",
    "sports": "🏆",
    "technology": "🚀",
}

with st.sidebar:
    st.markdown(
        "<div style='text-align:center;padding:0.5rem 0 0.25rem'>"
        "<span style='font-size:2.4rem'>🧞‍♂️</span><br>"
        "<span style='font-size:0.75rem;opacity:0.5'>NewsGenie</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    st.markdown("##### 📰 News Options")
    _categories = ["general", "entertainment", "finance", "politics", "sports", "technology"]
    category = st.selectbox(
        "Category",
        _categories,
        index=0,
        key="category_select",
        format_func=lambda c: f"{_CATEGORY_ICONS.get(c, '')}  {c.capitalize()}",
    )
    news_limit = st.slider(
        "Articles",
        min_value=3,
        max_value=SETTINGS.news_max_articles,
        value=min(10, SETTINGS.news_max_articles),
        step=1,
        key="news_limit",
    )

    # Placeholder for the loading indicator (filled during auto-fetch)
    _sidebar_status = st.empty()

    st.divider()

    # ── Service status ──
    st.markdown("##### ⚡ Services")

    _has_news = bool(SETTINGS.news_api_key) or SETTINGS.is_demo()
    _has_search = bool(SETTINGS.search_api_key and SETTINGS.search_api_base_url) or SETTINGS.is_demo()

    def _svc_row(label: str, available: bool, key: str, default: bool = True, help: str = "") -> bool:
        """Render a service row with status dot and toggle. Returns whether enabled."""
        cols = st.columns([0.08, 0.62, 0.30])
        dot = "🟢" if available else "🔴"
        cols[0].markdown(dot)
        display = label if available else f"{label} · *no key*"
        cols[1].markdown(display, help=help or None)
        enabled = cols[2].toggle(
            "on",
            value=default and available,
            key=key,
            disabled=not available,
            label_visibility="collapsed",
        )
        return enabled and available

    _llm_label = "LLM (Azure)" if SETTINGS.use_azure() else "LLM (OpenAI)"
    _svc_row(
        _llm_label,
        SETTINGS.has_llm_key() or SETTINGS.is_demo(),
        "_svc_llm",
        help="Generates answers from sources. Always active.",
    )
    use_news = _svc_row(
        "News API",
        _has_news,
        "_svc_news",
        help="Fetches headlines from NewsAPI.org for news and topic queries. Toggle off to answer from memory only.",
    )
    use_search = _svc_row(
        "Web Search",
        _has_search,
        "_svc_search",
        help="Runs a web search for fact-check and verification queries. Does not affect news fetches.",
    )

    st.divider()
    st.markdown("##### 💻 Session")
    if st.button("🗑️ Clear chat", use_container_width=True):
        st.session_state.pop("_cat_messages", None)
        st.session_state.pop("_last_category", None)
        st.session_state.pop("_news_memory", None)
        st.rerun()

    # Footer
    st.markdown(
        f"<div style='position:fixed;bottom:0.75rem;font-size:0.7rem;opacity:0.4'>"
        f"v{__version__}"
        f"</div>",
        unsafe_allow_html=True,
    )

# ── Per-category message & memory stores ──
if "_cat_messages" not in st.session_state:
    st.session_state["_cat_messages"] = {}  # category -> list[message]
if "_news_memory" not in st.session_state:
    st.session_state["_news_memory"] = {}  # category -> list[SourceItem]


def _messages() -> list[dict[str, Any]]:
    """Return the message list for the active category."""
    cat_msgs: dict[str, list[dict[str, Any]]] = st.session_state["_cat_messages"]
    if category not in cat_msgs:
        cat_msgs[category] = []
    return cat_msgs[category]


graph = _cached_graph()


def _build_init_state(
    query: str,
    *,
    chat_history: list[dict[str, str]] | None = None,
    memory: list[Any] | None = None,
) -> dict[str, Any]:
    """Build the initial LangGraph state dict for a query."""
    return {
        "user_query": query,
        "category": category,
        "intent": "GENERAL_QA",
        "decision": {"intent": "GENERAL_QA"},
        "chat_history": chat_history or [],
        "category_news_memory": memory or [],
        "news_limit": news_limit,
        "use_news": use_news,
        "use_search": use_search,
        "news_items": [],
        "search_items": [],
        "answer": "",
        "citations": [],
        "warnings": [],
        "errors": [],
        "meta": {},
    }


def _extract_sources(output: dict[str, Any]) -> list[str]:
    """Pull citation strings from graph output."""
    raw = output.get("citations")
    return [str(u) for u in cast(list[object], raw)] if isinstance(raw, list) else []

# ── Auto-load headlines when category changes ──
_prev_cat = st.session_state.get("_last_category")
if _prev_cat != category:
    st.session_state["_last_category"] = category
    # Skip the very first load if there are already messages (preserves chat on rerun)
    if _prev_cat is not None or not _messages():
        _auto_query = f"Latest {category} headlines"
        _messages().append({"role": "user", "content": _auto_query})

        _auto_state = _build_init_state(_auto_query)
        with _sidebar_status.container(), st.spinner(f"Fetching {category} headlines…"):
            _auto_out: dict[str, Any] = graph.invoke(_auto_state)
        _sidebar_status.empty()

        # Store fetched news items in per-category memory
        _fetched_items = _auto_out.get("news_items") or []
        if _fetched_items:
            st.session_state["_news_memory"][category] = _fetched_items
            log.info("Stored %d news items in memory for category=%s", len(_fetched_items), category)
        _messages().append(
            {
                "role": "assistant",
                "content": _auto_out.get("answer", ""),
                "sources": _extract_sources(_auto_out),
            }
        )
        st.rerun()

for m in _messages():
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("sources"):
            with st.expander("Sources"):
                for u in m["sources"]:
                    st.markdown(f"- {u}", unsafe_allow_html=True)

prompt = st.chat_input("Ask a question, or request news updates…")
if prompt:
    _messages().append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Build chat history for conversational context (this category only)
    _recent: list[dict[str, str]] = [
        {"role": m["role"], "content": m["content"]}
        for m in _messages()[-6:]  # last 3 exchanges
    ]

    init_state = _build_init_state(
        prompt,
        chat_history=_recent,
        memory=st.session_state.get("_news_memory", {}).get(category, []),
    )

    with st.chat_message("assistant"):
        with st.spinner("Thinking…"):
            out: dict[str, Any] = graph.invoke(init_state)

        # Update per-category news memory if new items were fetched
        _out_news = out.get("news_items") or []
        if _out_news:
            st.session_state["_news_memory"][category] = _out_news

        st.markdown(out.get("answer", "(no answer)"))
        sources = _extract_sources(out)
        if sources:
            with st.expander("Sources"):
                for u in sources:
                    st.markdown(f"- {u}", unsafe_allow_html=True)

    _messages().append({"role": "assistant", "content": out.get("answer", ""), "sources": sources})
