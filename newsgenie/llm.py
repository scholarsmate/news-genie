from __future__ import annotations

import functools
import logging
import re

import openai
from tenacity import retry, stop_after_attempt, wait_exponential_jitter

from newsgenie.config import SETTINGS

log = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _build_client() -> openai.OpenAI | openai.AzureOpenAI:
    """Create the appropriate OpenAI client based on config."""
    if SETTINGS.use_azure():
        log.info(
            "Using Azure OpenAI  endpoint=%s  deployment=%s",
            SETTINGS.azure_openai_endpoint,
            SETTINGS.azure_openai_deployment,
        )
        return openai.AzureOpenAI(
            api_key=SETTINGS.azure_openai_api_key,
            api_version=SETTINGS.azure_openai_api_version,
            azure_endpoint=SETTINGS.azure_openai_endpoint or "",
        )
    base = SETTINGS.openai_api_base_url.rstrip("/")
    return openai.OpenAI(
        api_key=SETTINGS.openai_api_key or "demo",
        base_url=f"{base}/v1",
    )


def _demo_answer(prompt: str) -> str:
    """Generate a realistic-looking demo response by synthesizing any sources found in the prompt."""

    # Extract source lines injected by node_compose
    source_lines = re.findall(r"\[(NEWS|WEB|MEMORY)\]\s*(.+)", prompt)

    if source_lines:
        # Build a grounded summary from the demo sources
        bullets: list[str] = []
        urls: list[str] = []
        for _kind, rest in source_lines:
            parts = [p.strip() for p in rest.split("|")]
            outlet = parts[0] if len(parts) > 0 else "Source"
            title = parts[1] if len(parts) > 1 else "Untitled"
            url = parts[2] if len(parts) > 2 else ""
            snippet = parts[3] if len(parts) > 3 else ""
            bullets.append(
                f"- **{title}** ([{outlet}]({url})): {snippet}" if url else f"- **{title}** ({outlet}): {snippet}"
            )
            if url:
                urls.append(url)

        body = "Here's a summary based on the available sources:\n\n" + "\n".join(bullets)

        body += "\n\n---\n*This is a **demo-mode** response. Add API keys in `.env` to get live, real-time answers.*"
        return body

    # General Q&A fallback (no sources)
    # Extract the user query from the prompt
    query_match = re.search(r"User query:\s*(.+?)(?:\n|$)", prompt)
    user_query = query_match.group(1).strip() if query_match else prompt[:200]

    return (
        f"Great question! Here's what I can tell you about **{user_query}**:\n\n"
        "In demo mode I don't have access to a live LLM, but in production NewsGenie would:\n"
        "1. Retrieve relevant news articles and web sources\n"
        "2. Synthesize them into a grounded, cited response\n"
        "3. Flag any conflicting evidence or gaps\n\n"
        f'To get a real answer to "{user_query}", add your `OPENAI_API_KEY` in `.env` and restart.\n\n'
        "---\n"
        "*Demo-mode response — no API keys configured.*"
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=8), reraise=True)
def chat(prompt: str, system: str = "You are a helpful assistant.", temperature: float = 0.2) -> str:
    if SETTINGS.is_demo() or not SETTINGS.has_llm_key():
        return _demo_answer(prompt)

    client = _build_client()
    model = SETTINGS.azure_openai_deployment if SETTINGS.use_azure() else SETTINGS.llm_model
    log.debug("LLM request  provider=%s  model=%s", "azure" if SETTINGS.use_azure() else "openai", model)

    response = client.chat.completions.create(
        model=model or SETTINGS.llm_model,
        temperature=temperature,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""
