"""
DeepSeek API client.

Chat completions endpoint: https://api.deepseek.com/v1/chat/completions
Model: deepseek-chat (default), deepseek-reasoner (optional)
Token: DEEPSEEK_API_KEY

Responses are cached in SQLite (llm_cache table) by prompt hash
to avoid paying twice for the same request.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from src.config import settings
from src.database import cache_llm_response, get_llm_cache, init_db

logger = logging.getLogger(__name__)

SOURCE_NAME = "DeepSeek"
BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


def _get_client() -> httpx.Client:
    key = settings.deepseek_api_key
    if not key:
        raise RuntimeError(f"{SOURCE_NAME}: DEEPSEEK_API_KEY not configured")
    return httpx.Client(
        base_url=BASE_URL,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        timeout=120.0,
    )


def chat(
    messages: list[dict[str, str]],
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.3,
    max_tokens: int = 2048,
    use_cache: bool = True,
) -> dict[str, Any]:
    prompt_key = json.dumps({"model": model, "messages": messages, "temperature": temperature}, sort_keys=True)

    if use_cache:
        conn = init_db(settings.db_path)
        cached = get_llm_cache(conn, prompt_key, model)
        if cached:
            logger.info(f"{SOURCE_NAME}: cache hit for prompt ({len(prompt_key)} chars)")
            return cached

    logger.info(f"{SOURCE_NAME}: calling {model} ({len(messages)} messages, {temperature=})")
    client = _get_client()
    try:
        response = client.post(
            "/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        if response.status_code != 200:
            raise RuntimeError(f"{SOURCE_NAME}: HTTP {response.status_code}: {response.text[:500]}")
        result = response.json()
    finally:
        client.close()

    choice = result.get("choices", [{}])[0]
    content = choice.get("message", {}).get("content", "")
    usage = result.get("usage", {})

    parsed = {
        "content": content,
        "model": result.get("model", model),
        "usage": {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "total_tokens": usage.get("total_tokens"),
        },
        "finish_reason": choice.get("finish_reason"),
        "source": SOURCE_NAME,
    }

    if use_cache:
        conn = init_db(settings.db_path)
        cache_llm_response(
            conn,
            prompt_key,
            parsed,
            model=model,
            tokens_input=usage.get("prompt_tokens"),
            tokens_output=usage.get("completion_tokens"),
        )

    return parsed


def chat_json(
    messages: list[dict[str, str]],
    *,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.1,
    max_tokens: int = 2048,
) -> dict[str, Any]:
    system_msg = messages[0] if messages and messages[0].get("role") == "system" else None
    if system_msg:
        if "JSON" not in system_msg.get("content", "").upper():
            messages[0]["content"] = system_msg["content"] + "\n\nAlways respond with valid JSON only. No markdown, no explanations."

    result = chat(messages, model=model, temperature=temperature, max_tokens=max_tokens)

    content = result.get("content", "{}").strip()
    if content.startswith("```"):
        content = content.split("\n", 1)[1] if "\n" in content else content[3:]
        content = content.rsplit("```", 1)[0] if "```" in content else content
        content = content.strip()

    try:
        result["parsed"] = json.loads(content)
    except json.JSONDecodeError:
        logger.warning(f"{SOURCE_NAME}: response was not valid JSON, returning raw content")
        result["parsed"] = {"raw": content, "_parse_error": True}

    return result
