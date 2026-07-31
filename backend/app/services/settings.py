"""设置服务：模型 / 执行参数 / 能力探测。"""
from __future__ import annotations

from typing import Any

from app.config import (
    DEFAULT_API_KEY,
    DEFAULT_BASE_URL,
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_PARALLEL,
    DEFAULT_RETRY_BASE_SECONDS,
    DEFAULT_STEP_TIMEOUT_SECONDS,
    DEFAULT_TEMPERATURE,
)
from app.storage import db

_MODEL_KEYS = {"model", "base_url", "api_key", "temperature", "max_tokens"}
_EXEC_KEYS = {"parallel", "step_timeout_seconds", "max_attempts", "retry_base_seconds"}


def _model_defaults() -> dict[str, Any]:
    return {
        "model": DEFAULT_MODEL,
        "base_url": DEFAULT_BASE_URL,
        "api_key": DEFAULT_API_KEY,
        "temperature": DEFAULT_TEMPERATURE,
        "max_tokens": DEFAULT_MAX_TOKENS,
    }


def _exec_defaults() -> dict[str, Any]:
    return {
        "parallel": DEFAULT_PARALLEL,
        "step_timeout_seconds": DEFAULT_STEP_TIMEOUT_SECONDS,
        "max_attempts": DEFAULT_MAX_ATTEMPTS,
        "retry_base_seconds": DEFAULT_RETRY_BASE_SECONDS,
    }


def get_model_settings() -> dict[str, Any]:
    saved = db.get_setting("model", {}) or {}
    merged = {**_model_defaults(), **saved}
    # API Key 永不明文回显
    merged["api_key"] = "***" if merged.get("api_key") else ""
    return merged


def save_model_settings(data: dict[str, Any]) -> None:
    clean = {k: v for k, v in (data or {}).items() if k in _MODEL_KEYS}
    current = db.get_setting("model", {}) or {}
    if clean.get("api_key") in ("", "***", None):
        clean.pop("api_key", None)  # 未修改则保留原值
    db.set_setting("model", {**current, **clean})


def get_execution_settings() -> dict[str, Any]:
    saved = db.get_setting("execution", {}) or {}
    return {**_exec_defaults(), **saved}


def save_execution_settings(data: dict[str, Any]) -> None:
    clean = {k: v for k, v in (data or {}).items() if k in _EXEC_KEYS}
    db.set_setting("execution", clean)


def get_capabilities() -> dict[str, Any]:
    cfg = get_model_settings()
    llm_ready = bool(cfg.get("api_key")) and bool(cfg.get("base_url"))
    return {
        "llm": llm_ready,
        "demo_mode": not llm_ready,
        "engine": "m1",
        "tool_count": len(db.list_tools()),
    }
