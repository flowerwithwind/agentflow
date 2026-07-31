"""报告 API（A6 / FR-07）：汇总报告查询与 Markdown 导出。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.storage import db

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _report_or_404(run_id: int) -> dict[str, Any]:
    """仅成功任务可导出报告；未找到或未成功均 404。"""
    row = db.get_run(run_id)
    if row is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if row["status"] != "succeeded" or not row["report"]:
        raise HTTPException(status_code=404, detail="任务未成功完成，无报告可导出")
    return dict(row)


@router.get("/{run_id}")
def get_report(run_id: int) -> dict[str, Any]:
    """查询任务汇总报告（JSON：Markdown 正文 + 元数据）。"""
    row = _report_or_404(run_id)
    return {
        "run_id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "report": row["report"],
        "total_tokens": row["total_tokens"],
        "total_duration_ms": row["total_duration_ms"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
    }


@router.get("/{run_id}/download")
def download_report(run_id: int) -> Response:
    """导出报告为 .md 附件（text/markdown）。"""
    row = _report_or_404(run_id)
    filename = f"agentflow-report-{run_id}.md"
    return Response(
        content=row["report"],
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
