"""任务 API：创建 / 列表 / 详情 / 取消 / 删除 / 事件。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.models import EventOut, RunCreate, RunOut, StepOut
from app.services import planner
from app.storage import db

router = APIRouter(prefix="/api/runs", tags=["runs"])


def _run_out(row) -> RunOut:
    return RunOut(**dict(row))


def _step_out(row) -> StepOut:
    return StepOut(
        id=row["id"], run_id=row["run_id"], step_key=row["step_key"], seq=row["seq"],
        name=row["name"], role=row["role"], kind=row["kind"], tool_key=row["tool_key"],
        prompt=row["prompt"],
        depends_on=db.jloads(row["depends_on"], []), status=row["status"],
        output=db.jloads(row["output_json"], None),
        tokens_in=row["tokens_in"], tokens_out=row["tokens_out"], duration_ms=row["duration_ms"],
        attempts=row["attempts"], error=row["error"],
        created_at=row["created_at"], finished_at=row["finished_at"],
    )


@router.post("", status_code=201)
def create_run(body: RunCreate) -> RunOut:
    run_id = db.create_run(body.title, body.input_text, db.now_iso())
    # A2：创建后立即规划并落库，状态 pending → planning → succeeded / failed
    planner.plan_run(run_id)
    row = db.get_run(run_id)
    return _run_out(row)


@router.get("")
def list_runs(status: str = "", query: str = "", page: int = 1, page_size: int = 20) -> dict[str, Any]:
    rows, total = db.list_runs(
        status=status, query=query, page=max(page, 1), page_size=min(max(page_size, 1), 100),
    )
    return {"total": total, "items": [_run_out(r) for r in rows]}


@router.get("/{run_id}")
def get_run(run_id: int) -> dict[str, Any]:
    row = db.get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"run": _run_out(row), "steps": [_step_out(s) for s in db.list_steps(run_id)]}


@router.post("/{run_id}/cancel")
def cancel_run(run_id: int) -> RunOut:
    row = db.get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    if row["status"] in ("succeeded", "failed", "cancelled"):
        raise HTTPException(status_code=409, detail=f"任务已处于终态 {row['status']}")
    db.update_run(run_id, status="cancelled", finished_at=db.now_iso())
    db.insert_event(run_id, "run_cancelled", {"run_id": run_id})
    return _run_out(db.get_run(run_id))


@router.delete("/{run_id}")
def delete_run(run_id: int) -> dict[str, Any]:
    row = db.get_run(run_id)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    db.delete_run(run_id)
    return {"deleted": run_id}


@router.get("/{run_id}/events")
def list_events(run_id: int, after: int = 0, limit: int = 500) -> list[EventOut]:
    if not db.get_run(run_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return [
        EventOut(
            id=r["id"], run_id=r["run_id"], step_id=r["step_id"], seq=r["seq"],
            type=r["type"], payload=db.jloads(r["payload_json"], None), created_at=r["created_at"],
        )
        for r in db.list_events(run_id, after=after, limit=min(limit, 2000))
    ]