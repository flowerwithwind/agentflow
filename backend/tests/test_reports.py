"""报告汇总与导出测试（A6 / FR-07）：成功产出报告、引用跳转、失败无报告、.md 导出。"""
from __future__ import annotations

import time

from app.storage import db

TERMINAL = ("succeeded", "failed", "cancelled")


def _wait_run(run_id, timeout=15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if db.get_run(run_id)["status"] in TERMINAL:
            return db.get_run(run_id)
        time.sleep(0.02)
    raise AssertionError("run 未到达终态")


def test_report_generated_on_success(client):
    r = client.post("/api/runs", json={"title": "竞争分析", "input_text": "请分析三家竞争产品的最新动态并给出建议。"}).json()
    _wait_run(r["id"])
    resp = client.get(f"/api/reports/{r['id']}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == r["id"]
    assert data["status"] == "succeeded"
    assert "任务报告" in data["report"]
    assert "步骤索引" in data["report"]
    assert "步骤 1." in data["report"]
    assert "执行概览" in data["report"]
    assert data["total_tokens"] >= 0
    assert data["total_duration_ms"] is not None


def test_report_citations_point_to_dependencies(client):
    r = client.post("/api/runs", json={"title": "数据核对", "input_text": "核对订单与库存数据的一致性差异。"}).json()
    _wait_run(r["id"])
    data = client.get(f"/api/reports/{r['id']}").json()
    report = data["report"]
    # 步骤索引锚点
    assert "#步骤-1" in report
    assert "#步骤-2" in report
    # compare 步骤（依赖 extract）与 report 步骤（依赖 compare）的引用行
    assert "> 引用：[步骤 1：" in report
    assert "> 引用：[步骤 2：" in report
    # 报告步骤不嵌套重复正文
    assert "报告正文已由引擎按步骤汇总" in report


def test_report_failed_run_no_report(client):
    rid = db.create_run("故障任务", "触发失败", db.now_iso())
    db.update_run(rid, status="failed", error="模拟失败", finished_at=db.now_iso())
    assert client.get(f"/api/reports/{rid}").status_code == 404
    assert client.get(f"/api/reports/{rid}/download").status_code == 404


def test_report_download_markdown(client):
    r = client.post("/api/runs", json={"title": "竞争分析", "input_text": "请分析三家竞争产品的最新动态并给出建议。"}).json()
    _wait_run(r["id"])
    meta = client.get(f"/api/reports/{r['id']}").json()
    resp = client.get(f"/api/reports/{r['id']}/download")
    assert resp.status_code == 200
    assert "text/markdown" in resp.headers["content-type"]
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.text == meta["report"]


def test_report_404_unknown(client):
    assert client.get("/api/reports/9999").status_code == 404
    assert client.get("/api/reports/9999/download").status_code == 404
