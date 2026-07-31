"""设置 API。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.models import SettingsOut
from app.services import settings as settings_svc
from app.storage import db

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings() -> SettingsOut:
    return SettingsOut(
        model=settings_svc.get_model_settings(),
        execution=settings_svc.get_execution_settings(),
        capabilities=settings_svc.get_capabilities(),
    )


@router.put("")
def update_settings(body: dict[str, Any]) -> SettingsOut:
    if "model" in body:
        settings_svc.save_model_settings(body["model"])
    if "execution" in body:
        settings_svc.save_execution_settings(body["execution"])
    return get_settings()


@router.post("/clear-data")
def clear_data() -> dict:
    """数据管理（A8/A9）：清空全部任务数据，保留工具注册表与模型/执行设置。"""
    cleared = db.clear_runs()
    return {"cleared": "runs", "count": cleared}

