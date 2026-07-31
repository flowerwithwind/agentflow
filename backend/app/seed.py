"""启动种子：内置工具注册。"""
from __future__ import annotations

from app.storage import db


def ensure_seed_tools() -> None:
    db.seed_builtin_tools()
