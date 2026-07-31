"""Pydantic 数据模型与枚举。"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def now_iso() -> str:
    # 全项目统一使用本地时间（无时区），避免 UI 展示混乱
    return datetime.now().isoformat(timespec="seconds")  # noqa: DTZ005


class RunStatus(StrEnum):
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class StepKind(StrEnum):
    LLM = "llm"
    TOOL = "tool"
    APPROVAL = "approval"
    REPORT = "report"


class ToolOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    key: str
    name: str
    description: str = ""
    params: dict[str, Any] = {}
    sensitive: bool = False
    is_builtin: bool = False


class ToolIn(BaseModel):
    key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=64)
    description: str = ""
    params: dict[str, Any] = {}
    sensitive: bool = False


class RunCreate(BaseModel):
    title: str = Field(min_length=1, max_length=64)
    input_text: str = Field(min_length=1, max_length=4000)
    parallel: int = Field(default=4, ge=1, le=16)
    allow_sensitive: bool = False


class RunOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    title: str
    input_text: str
    status: str
    error: str | None = None
    report: str | None = None
    total_tokens: int = 0
    total_duration_ms: int | None = None
    created_at: str
    updated_at: str
    finished_at: str | None = None


class StepOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    run_id: int
    step_key: str
    seq: int
    name: str
    role: str
    kind: str
    tool_key: str | None = None
    depends_on: list[str] = []
    status: str
    output: dict[str, Any] | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    duration_ms: int | None = None
    attempts: int = 0
    error: str | None = None
    created_at: str
    finished_at: str | None = None


class EventOut(BaseModel):
    id: int
    run_id: int
    step_id: int | None = None
    seq: int
    type: str
    payload: dict[str, Any] | None = None
    created_at: str


class ApprovalIn(BaseModel):
    action: str = Field(pattern=r"^(approve|reject)$")
    reason: str = Field(default="", max_length=500)


class SettingsOut(BaseModel):
    model: dict[str, Any]
    execution: dict[str, Any]
    capabilities: dict[str, Any]
