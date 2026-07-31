"""共享 LLM 调用层：OpenAI 兼容 chat/completions + JSON 结构化输出。"""
from __future__ import annotations

import json
from typing import Any

import httpx

from app.config import (
    DEFAULT_API_KEY,
    DEFAULT_BASE_URL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
)
from app.storage import db

LLM_TIMEOUT_SECONDS = 60.0


def get_llm_config() -> dict[str, Any]:
    """读取 LLM 配置：app/config.py 默认值，settings 表可覆盖。"""
    saved = db.get_setting("model", {}) or {}
    return {
        "base_url": saved.get("base_url") or DEFAULT_BASE_URL,
        "model": saved.get("model") or DEFAULT_MODEL,
        "api_key": saved.get("api_key") or DEFAULT_API_KEY,
        "temperature": saved.get("temperature", DEFAULT_TEMPERATURE),
        "max_tokens": saved.get("max_tokens", DEFAULT_MAX_TOKENS),
    }


def has_api_key(cfg: dict[str, Any] | None = None) -> bool:
    cfg = cfg or get_llm_config()
    return bool(cfg.get("api_key"))


def chat_completion(
    system_prompt: str,
    user_prompt: str,
    cfg: dict[str, Any] | None = None,
    timeout_seconds: float | None = None,
) -> tuple[str, dict[str, Any] | None]:
    """调用 OpenAI 兼容 chat/completions 接口，返回 (content, usage)。"""
    cfg = cfg or get_llm_config()
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": cfg.get("temperature", DEFAULT_TEMPERATURE),
        "max_tokens": cfg.get("max_tokens", DEFAULT_MAX_TOKENS),
    }
    resp = httpx.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {cfg['api_key']}"},
        timeout=timeout_seconds or LLM_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    return content, data.get("usage")


def parse_json_object(content: str) -> dict[str, Any]:
    """解析 LLM 输出为 JSON 对象：剥离 Markdown 代码块，失败抛 ValueError。"""
    text = content.strip()
    text = text.removeprefix("```json").removeprefix("```").strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM 输出不是合法 JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise TypeError("LLM 输出不是 JSON 对象")
    return data


def usage_to_tokens(usage: dict[str, Any] | None) -> tuple[int, int]:
    usage = usage or {}
    return int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
