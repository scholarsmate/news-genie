# NewsGenie — S.T.A.R. Report

> **Project**: NewsGenie — An AI-Powered Information and News Assistant
> **Repository**: [github.com/scholarsmate/news-genie](https://github.com/scholarsmate/news-genie)
> **Version**: 0.1.0

---

## Situation

People struggle to keep up with real-time, reliable news in today's fast-paced digital world. Users face challenges such as filtering misinformation, finding trustworthy sources, and securing timely answers to general queries — all in one place. Modern news consumption is fragmented and overwhelming, making it difficult to stay updated with accurate news, filter unreliable content, and access personalised feeds alongside general information quickly.

**How NewsGenie addresses this:**

| Challenge | Implementation |
| --- | --- |
| **Real-time news** | `_fetch_news_live()` in `newsgenie/tools/news.py` calls the NewsAPI `/v2/top-headlines` and `/v2/everything` endpoints with `sortBy=publishedAt`, returning the latest articles sorted by recency. |
| **Misinformation filtering** | `trust_score()` in `newsgenie/tools/trust.py` promotes articles from a curated list of `HIGH_REPUTATION_DOMAINS` (Reuters, AP, BBC, WSJ, etc.) and penalises items with missing snippets or titles. |
| **Trustworthy sources** | `rank_sources()` in `newsgenie/tools/trust.py` scores and sorts every batch of articles before they reach the LLM, ensuring the most reputable sources appear first and are prioritised in answers. |
| **Unified platform** | `node_compose()` in `newsgenie/workflow.py` merges NEWS, WEB-SEARCH, and MEMORY sources into a single structured LLM prompt, delivering one cohesive answer per user query. |

---

## Task

The core task was to build NewsGenie as a unified platform satisfying four objectives:

### 1. Handle Conversations — AI Chatbot That Distinguishes Query Types

NewsGenie classifies every user input into one of six intent types via `classify_intent()` in `newsgenie/workflow.py`:

```python
Intent = Literal["NEWS_CATEGORY", "NEWS_TOPIC", "GENERAL_QA", "FACT_CHECK", "MIXED", "FOLLOW_UP"]
```

The classification uses keyword-based NLP across three tuples:

- **`news_words`** (18 terms) — triggers `NEWS_CATEGORY` or `NEWS_TOPIC` intents
- **`fact_words`** (9 terms) — triggers `FACT_CHECK` intent
- **`fact_prefixes`** (7 verb prefixes) — detects yes/no verification questions

When news keywords match and capitalised entities are found, the system classifies the query as `NEWS_TOPIC` and extracts the entities (e.g. "Apple", "Tesla"). If no news or fact keywords match, the system defaults to `GENERAL_QA` and answers from the LLM without fetching external sources.

Conversation context is maintained by passing the last 3 exchanges (6 messages) from `st.session_state` as `chat_history` into the LangGraph workflow. The `node_compose()` function formats this history into a `"Recent conversation:"` block, with assistant turns truncated to 400 characters for prompt efficiency.

**Key files:**

- `newsgenie/schema.py` — `Intent`, `Category`, `IntentDecision` type definitions
- `newsgenie/workflow.py` — `classify_intent()` function
- `app.py` — `_build_init_state()` passes `chat_history` into the graph

### 2. Integrate APIs — Real-Time News API + Web Search

Two external APIs are integrated:

**NewsAPI (newsapi.org):**

- Endpoints: `/v2/top-headlines` (category browsing) and `/v2/everything` (topic search)
- Implemented in `newsgenie/tools/news.py` via `_fetch_news_live()`
- If the user provides a query → `EVERYTHING` endpoint with `q=` parameter; otherwise → `TOP_HEADLINES` with `category=` parameter
- Results are parsed from the `.articles[]` response array

**Brave Search API:**

- Implemented in `newsgenie/tools/search.py` via `_search_live()`
- Called with `X-Subscription-Token` header, parses `web.results` from the JSON response
- Used for fact-checking and verification queries

Both APIs are wrapped with:

- **TTL caching** (`TTLCache` in `newsgenie/util/cache.py`, default 180 seconds)
- **Retry logic** (Tenacity `@retry` with exponential backoff + jitter, 3 attempts)
- **Request timeouts** (12 seconds per call)
- **Demo mode fallback** (synthetic data when API keys are unavailable)
- **Demo mode fallback** (synthetic data when API keys are unavailable)

### 3. Manage Workflow — LangGraph-Based Pipeline

The entire processing pipeline is built as a `StateGraph(AgentState)` in `newsgenie/workflow.py` via `build_graph()`:

```text
ingest → classify → retrieve → compose → finalize → END
```

| Node | Purpose |
| --- | --- |
| `node_ingest` | Initialises/clears transient state fields (`errors`, `warnings`, `citations`, `news_items`, `search_items`) |
| `node_classify` | Calls `classify_intent()` and stores the `IntentDecision` in state |
| `node_retrieve` | Conditionally fetches news and/or web search results based on intent type and user-controlled toggles (`use_news` / `use_search`), then ranks results via `rank_sources()` |
| `node_compose` | Merges all sources (tagged `[NEWS]`, `[WEB]`, `[MEMORY]`), builds a context-aware prompt with conversation history, calls the LLM, and extracts enriched citations |
| `node_finalize` | Appends any accumulated warnings/errors as a `---` footer block to the answer |

The `AgentState` TypedDict (`newsgenie/schema.py`) carries 15+ fields through the pipeline, including `user_query`, `category`, `intent`, `decision`, `chat_history`, `category_news_memory`, `news_items`, `search_items`, `answer`, `citations`, `warnings`, `errors`, and `meta`.

The compiled graph is cached per Streamlit server lifetime via `@st.cache_resource`.

### 4. Deliver an Intuitive UI — Streamlit Interface

The frontend (`app.py`) provides:

- **Category selector**: dropdown with 6 categories (general, entertainment, finance, politics, sports, technology), each with an emoji icon
- **Article limit slider**: configurable from 3 to `NEWS_MAX_ARTICLES` (default 20)
- **Service status panel**: green/red status dots with toggles for LLM, News API, and Web Search — each with an info tooltip and "no key" label when unavailable
- **Chat interface**: `st.chat_input()` for queries, `st.chat_message()` bubbles for conversation, expandable "Sources" section on each response
- **Auto-load headlines**: when the user switches categories, the system automatically fetches fresh headlines
- **Clear chat**: one-click session reset button

---

## Actions

### Action 1 — Chatbot Development

The chatbot's NLP-based intent classification (`classify_intent()` in `newsgenie/workflow.py`) uses:

- **Keyword matching**: three curated tuples — `news_words` (18 news-related terms), `fact_words` (9 verification terms), and `fact_prefixes` (7 verb prefixes for yes/no questions)
- **Entity extraction**: capitalised tokens > 2 characters are extracted as named entities for `NEWS_TOPIC` classification
- **Intent taxonomy**: six distinct intents (`NEWS_CATEGORY`, `NEWS_TOPIC`, `GENERAL_QA`, `FACT_CHECK`, `MIXED`, `FOLLOW_UP`) with a `GENERAL_QA` fallback default
- **LLM response generation**: `chat()` in `newsgenie/llm.py` sends structured prompts to OpenAI / Azure OpenAI with full source context and conversation history

### Action 2 — API and Web Search Integration

| Component | File | Function | Details |
| --- | --- | --- | --- |
| News API (live) | `newsgenie/tools/news.py` | `_fetch_news_live()` | Calls NewsAPI with `requests.get()`, `X-Api-Key` header, 12s timeout |
| News API (entry) | `newsgenie/tools/news.py` | `fetch_news()` | Demo fallback + TTL cache wrapper |
| News API (demo) | `newsgenie/tools/news.py` | `_demo_items()` | 6 synthetic articles per category (6 categories × 6 = 36 demo articles) |
| Web Search (live) | `newsgenie/tools/search.py` | `_search_live()` | Calls Brave Search API with `X-Subscription-Token`, parses `web.results` |
| Web Search (entry) | `newsgenie/tools/search.py` | `web_search()` | Demo fallback + TTL cache wrapper |
| Web Search (demo) | `newsgenie/tools/search.py` | `_demo_search()` | Topic-aware synthetic search results |

### Action 3 — Workflow Optimisation

- **LangGraph pipeline**: 5-node `StateGraph` compiled via `g.compile()` in `build_graph()`
- **Retry with exponential backoff**: Tenacity `@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(...))` on `_safe_fetch_news()` and `chat()`
- **Graceful degradation**: API fetch errors are caught, logged, and appended to `state["errors"]` — the pipeline continues with whatever data was successfully retrieved
- **Demo mode fallback**: when no API keys are configured, the system automatically switches to demo mode (`config.py: is_demo()`) with synthetic data for all three services (LLM, News, Search)
- **Warning/error footer**: `node_finalize()` appends accumulated warnings and errors as a formatted footer so users see transparent diagnostics

### Action 4 — User Interface Deployment

- **Session management**: per-category chat histories (`_cat_messages`) and news memory (`_news_memory`) stored in `st.session_state`
- **Per-category isolation**: switching categories preserves separate conversation threads
- **Loading indicators**: `st.spinner()` shown during headline fetches and query processing
- **Source attribution**: each response includes an expandable "Sources" section with linked citations (title, outlet, URL)
- **Responsive design**: `layout="wide"` fills the viewport; sidebar houses all controls; main area is dedicated to conversation

### Action 5 — Error Handling and Performance Optimisation

| Strategy | Implementation |
| --- | --- |
| **Custom exceptions** | `NewsGenieError` → `ToolError` (API/parsing) and `ConfigurationError` (missing config) in `newsgenie/util/errors.py` |
| **Missing API keys** | `is_demo()` auto-detects, shows info banner, service dots turn 🔴 with "no key" label |
| **API failure handling** | `try/except` blocks in `node_retrieve()` catch errors and append to `state["errors"]` — pipeline never crashes |
| **LLM failure handling** | `try/except` in `node_compose()` sets a friendly fallback message |
| **TTL caching** | `TTLCache` (180s default, configurable via `CACHE_TTL_SECONDS`) on News API and Web Search calls |
| **Graph caching** | `@st.cache_resource` builds the compiled graph once per server lifetime |
| **LLM client caching** | `@functools.lru_cache(maxsize=1)` on `_build_client()` prevents repeated client construction |
| **Request timeouts** | 12-second timeout on all external HTTP requests |
| **Prompt size control** | Assistant messages in conversation history truncated to 400 characters |

---

## Result

### 1. Interactive AI-Powered Assistant

NewsGenie delivers instant, contextual responses to general queries while providing real-time, curated news updates — all within a single chat interface. The system intelligently routes queries through intent classification, fetches relevant sources, and synthesises coherent answers citing specific articles.

### 2. Fully Integrated System

The platform seamlessly combines three data sources through a LangGraph-based pipeline:

- **NewsAPI** for real-time headline and topic-based article retrieval
- **Brave Search** for web-based fact-checking and verification
- **Conversation memory** for previously fetched articles per category

All sources are tagged (`[NEWS]`, `[WEB]`, `[MEMORY]`), trust-ranked, and fed to the LLM in a unified prompt.

### 3. User-Friendly Streamlit Interface

The Streamlit frontend features:

- Dark theme with responsive wide layout
- Per-category session management with separate chat histories
- Service status panel with live API availability indicators and toggles
- Category-specific emoji icons and auto-loading headlines
- Expandable source citations on every response
- One-click session clearing

### 4. Fallback Mechanisms and Optimisation

The system ensures reliable performance through multiple layers:

- **Demo mode**: fully functional without any API keys, using 36 synthetic news articles, topic-aware search results, and generated LLM responses
- **Retry logic**: 3-attempt exponential backoff with jitter on all external API calls
- **Graceful degradation**: individual API failures are captured and reported to the user while the pipeline continues with available data
- **Multi-layer caching**: TTL cache on API calls (180s), `@st.cache_resource` on the LangGraph, `@lru_cache` on the LLM client
- **User control**: per-query toggles allow disabling News API or Web Search independently

---

## Architecture Summary

```text
┌──────────────────────────────────────────────────────────┐
│                    Streamlit UI (app.py)                 │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │  Sidebar   │  │  Chat Input  │  │  Chat Messages   │  │
│  │ • Category │  │              │  │  + Sources       │  │
│  │ • Toggles  │  │              │  │                  │  │
│  │ • Status   │  │              │  │                  │  │
│  └────────────┘  └──────┬───────┘  └──────────────────┘  │
└─────────────────────────┼────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│              LangGraph Workflow (workflow.py)            │
│                                                          │
│  ingest → classify → retrieve → compose → finalize → END │
│                          │          │                    │
│                    ┌─────┴─────┐    │                    │
│                    │           │    ▼                    │
│                    ▼           ▼   LLM                   │
│                News API    Web Search  (llm.py)          │
│              (news.py)   (search.py)                     │
│                    │           │                         │
│                    ▼           ▼                         │
│                  trust.py (rank_sources)                 │
└──────────────────────────────────────────────────────────┘
```

---

## Test Coverage

29 unit tests across 5 test files:

| Test File | Tests | Coverage Area |
| --- | --- | --- |
| `tests/test_cache.py` | 4 | TTL miss, hit, expiry, `get_or_set` |
| `tests/test_intent.py` | 13 | All 6 intent types, edge cases, entity extraction |
| `tests/test_llm.py` | 3 | Demo answer generation paths |
| `tests/test_search.py` | 5 | Topic cleaning, demo search, bonus results |
| `tests/test_trust.py` | 4 | Score bounds, reputation boost, domain parsing, ranking |

---

## Key Files Reference

| File | Role |
| --- | --- |
| `app.py` | Streamlit UI, session management, graph invocation |
| `newsgenie/schema.py` | Type definitions (`Intent`, `Category`, `AgentState`, `SourceItem`) |
| `newsgenie/workflow.py` | LangGraph pipeline + intent classification |
| `newsgenie/llm.py` | LLM client (OpenAI/Azure) + demo fallback |
| `newsgenie/config.py` | Environment-based configuration (`Settings` dataclass) |
| `newsgenie/tools/news.py` | NewsAPI integration (live + demo) |
| `newsgenie/tools/search.py` | Brave web search integration (live + demo) |
| `newsgenie/tools/trust.py` | Source credibility scoring and ranking |
| `newsgenie/util/cache.py` | TTL cache utility |
| `newsgenie/util/errors.py` | Custom exception hierarchy |
