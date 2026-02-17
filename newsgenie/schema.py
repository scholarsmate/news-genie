from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

Intent = Literal["NEWS_CATEGORY", "NEWS_TOPIC", "GENERAL_QA", "FACT_CHECK", "MIXED", "FOLLOW_UP"]
Category = Literal["technology", "finance", "sports", "politics", "entertainment", "general"]


class IntentDecision(TypedDict):
    intent: Intent
    category: NotRequired[Category]
    timeframe: NotRequired[str]
    entities: NotRequired[list[str]]
    answer_mode: NotRequired[str]


class SourceItem(TypedDict):
    title: str
    url: str
    outlet: str
    published_at: str
    snippet: str
    score: NotRequired[float]


class AgentState(TypedDict):
    user_query: str
    category: Category
    intent: Intent
    decision: IntentDecision
    news_limit: int

    use_news: bool
    use_search: bool

    chat_history: list[dict[str, str]]
    category_news_memory: list[SourceItem]
    news_items: list[SourceItem]
    search_items: list[SourceItem]

    answer: str
    citations: list[str]
    warnings: list[str]
    errors: list[str]
    meta: dict[str, Any]
