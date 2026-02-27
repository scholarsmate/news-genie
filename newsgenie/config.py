from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    return v if v not in (None, "") else default


def _env_int(name: str, default: int, *, min_value: int | None = None, max_value: int | None = None) -> int:
    raw = _env(name, str(default))
    try:
        value = int(raw) if raw is not None else default
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {name}: expected integer, got {raw!r}") from exc

    if min_value is not None and value < min_value:
        raise ValueError(f"Invalid {name}: expected >= {min_value}, got {value}")
    if max_value is not None and value > max_value:
        raise ValueError(f"Invalid {name}: expected <= {max_value}, got {value}")
    return value


def _env_choice(name: str, default: str, choices: set[str]) -> str:
    raw = (_env(name, default) or default).lower()
    if raw not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"Invalid {name}: expected one of [{allowed}], got {raw!r}")
    return raw


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None = _env("OPENAI_API_KEY")
    openai_api_base_url: str = _env("OPENAI_API_BASE_URL", "https://api.openai.com") or "https://api.openai.com"
    llm_model: str = _env("LLM_MODEL", "gpt-4.1-mini") or "gpt-4.1-mini"

    # Azure OpenAI (takes priority over standard OpenAI when set)
    azure_openai_api_key: str | None = _env("AZURE_OPENAI_API_KEY")
    azure_openai_endpoint: str | None = _env("AZURE_OPENAI_ENDPOINT")
    azure_openai_api_version: str = _env("AZURE_OPENAI_API_VERSION", "2023-12-01-preview") or "2023-12-01-preview"
    azure_openai_deployment: str | None = _env("AZURE_OPENAI_DEPLOYMENT")

    news_api_key: str | None = _env("NEWS_API_KEY")
    news_country: str = _env("NEWS_COUNTRY", "us") or "us"
    news_lang: str = _env("NEWS_LANG", "en") or "en"
    news_max_articles: int = _env_int("NEWS_MAX_ARTICLES", 20, min_value=3, max_value=100)

    search_api_key: str | None = _env("SEARCH_API_KEY")
    search_api_base_url: str | None = _env("SEARCH_API_BASE_URL")

    cache_ttl_seconds: int = _env_int("CACHE_TTL_SECONDS", 180, min_value=1, max_value=86_400)
    log_level: str = _env("LOG_LEVEL", "INFO") or "INFO"

    demo_mode: str = _env_choice("DEMO_MODE", "auto", {"auto", "true", "false"})

    def use_azure(self) -> bool:
        """True when Azure OpenAI credentials are configured."""
        return bool(self.azure_openai_api_key and self.azure_openai_endpoint)

    def has_llm_key(self) -> bool:
        """True when *any* LLM backend (Azure or standard) has a key."""
        return bool(self.azure_openai_api_key or self.openai_api_key)

    def is_demo(self) -> bool:
        if self.demo_mode == "true":
            return True
        if self.demo_mode == "false":
            return False
        return (not self.has_llm_key()) and (self.news_api_key is None) and (self.search_api_key is None)


SETTINGS = Settings()
