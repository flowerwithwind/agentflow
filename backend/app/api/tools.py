"""工具注册表 API（A4 / FR-04）。

- GET  /api/tools              内置 + 自定义工具列表；
- POST /api/tools              注册自定义工具（仅存参数定义，不存实现）；
- PUT  /api/tools/{key}        更新自定义工具（内置工具不可修改）；
- DELETE /api/tools/{key}      删除自定义工具（内置工具不可删除）。
"""
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


@router.put("/{key}")
def update_tool(key: str, body: ToolIn) -> ToolOut:
    row = db.get_tool_by_key(key)
    if row is None:
        raise HTTPException(status_code=404, detail="工具不存在")
    if bool(row["is_builtin"]):
        raise HTTPException(status_code=409, detail="内置工具不可修改")
    db.update_tool(key, body.name, body.description, body.params, body.sensitive)
    return _row_to_out(db.get_tool_by_key(key))


@router.delete("/{key}")
def delete_tool(key: str) -> dict[str, str]:
    row = db.get_tool_by_key(key)
    if row is None:
        raise HTTPException(status_code=404, detail="工具不存在")
    if bool(row["is_builtin"]):
        raise HTTPException(status_code=409, detail="内置工具不可删除")
    db.delete_tool(key)
    return {"deleted": key}
