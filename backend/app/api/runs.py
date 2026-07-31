"""任务 API：创建 / 列表 / 详情 / 取消 / 审批 / 删除 / 事件 / SSE 事件流。"""
from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import StreamingResponse

from app.models import ApprovalIn, EventOut, RunCreate, RunOut, StepOut
from app.services import executor
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
    if body.parallel != 4:
        merged = {**db.get_setting("execution", {}), "parallel": body.parallel}
        db.set_setting("execution", merged)
    # A3：后台线程完整执行（规划 → DAG 调度），接口立即返回
    executor.start_run(run_id)
    return _run_out(db.get_run(run_id))


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
    if not db.get_run(run_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        executor.request_cancel(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _run_out(db.get_run(run_id))


@router.post("/steps/{step_id}/approve")
def approve_step(step_id: int, body: ApprovalIn) -> dict[str, Any]:
    """审批接口（A3）：步骤处于 waiting_approval 时可 approve / reject。"""
    if db.get_step(step_id) is None:
        raise HTTPException(status_code=404, detail="步骤不存在")
    try:
        executor.approve_step(step_id, body.action, body.reason)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "step_id": step_id,
        "action": body.action,
        "reason": body.reason,
        "status": "approved" if body.action == "approve" else "rejected",
    }


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


# ---------------------------------------------------------------- SSE 事件流（A5）

_TERMINAL_STATUSES = ("succeeded", "failed", "cancelled")


def _sse_event(ev) -> str:
    """单条 SSE 消息：id=seq、event=type、data=JSON（单行，兼容任何 SSE 客户端）。"""
    data = json.dumps(
        {
            "id": ev["id"],
            "seq": ev["seq"],
            "step_id": ev["step_id"],
            "type": ev["type"],
            "payload": db.jloads(ev["payload_json"], None),
            "created_at": ev["created_at"],
        },
        ensure_ascii=False,
    )
    return f"id: {ev['seq']}\nevent: {ev['type']}\ndata: {data}\n\n"


def _event_stream(run_id: int, after: int):
    """事件流生成器：轮询增量事件；任务进入终态且事件排空后结束。"""
    last_seq = after
    while True:
        events = db.list_events(run_id, after=last_seq, limit=200)
        for ev in events:
            last_seq = ev["seq"]
            yield _sse_event(ev)
        run = db.get_run(run_id)
        if run is not None and run["status"] in _TERMINAL_STATUSES and not events:
            return
        time.sleep(0.3)


@router.get("/{run_id}/events/stream")
def stream_events(
    run_id: int,
    after: int = 0,
    last_event_id: str | None = Header(default=None),
) -> StreamingResponse:
    """SSE 事件流（A5）：支持 after 查询参数与 Last-Event-ID 断线续传（增量协议）。"""
    if not db.get_run(run_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    if last_event_id is not None and last_event_id.isdigit():
        after = max(after, int(last_event_id))
    return StreamingResponse(
        _event_stream(run_id, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
