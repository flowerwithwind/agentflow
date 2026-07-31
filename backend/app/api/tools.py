"""工具注册表 API。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models import ToolIn, ToolOut
from app.storage import db

router = APIRouter(prefix="/api/tools", tags=["tools"])


def _row_to_out(row) -> ToolOut:
    return ToolOut(
        id=row["id"], key=row["key"], name=row["name"],
        description=row["description"] or "", params=db.jloads(row["params_json"], {}),
        sensitive=bool(row["sensitive"]), is_builtin=bool(row["is_builtin"]),
    )


@router.get("")
def list_tools() -> list[ToolOut]:
    return [_row_to_out(r) for r in db.list_tools()]


@router.post("", status_code=201)
def create_tool(body: ToolIn) -> ToolOut:
    if db.get_tool_by_key(body.key):
        raise HTTPException(status_code=409, detail="工具 key 已存在")
    db.create_tool(body.key, body.name, body.description, body.params, body.sensitive)
    row = db.get_tool_by_key(body.key)
    return _row_to_out(row)
