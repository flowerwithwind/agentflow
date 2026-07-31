"""设置 API。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.models import SettingsOut
from app.services import settings as settings_svc

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
