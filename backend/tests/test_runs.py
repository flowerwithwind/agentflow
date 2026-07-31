"""任务 CRUD 与事件测试（A3：创建即异步执行，状态 pending → planning → running → succeeded/failed/cancelled）。"""
from __future__ import annotations

import time

from app.services import executor, planner
from app.storage import db

TERMINAL = ("succeeded", "failed", "cancelled")


def _payload(title="竞争分析", text="请分析三家竞争产品的最新动态并给出建议。"):
    return {"title": title, "input_text": text}


def _wait_until(pred, timeout=10.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return False


def _wait_run(run_id, timeout=15.0):
    assert _wait_until(lambda: db.get_run(run_id)["status"] in TERMINAL, timeout), "run 未到达终态"
    return db.get_run(run_id)


def test_create_run(client):
    r = client.post("/api/runs", json=_payload())
    assert r.status_code == 201
    run = r.json()
    assert run["title"] == "竞争分析"
    assert run["id"] > 0
    # A3：创建即返回（后台线程执行），轮询至终态
    done = _wait_run(run["id"])
    assert done["status"] == "succeeded"
    types = [e["type"] for e in db.list_events(run["id"])]
    assert types[:3] == ["run_planning", "run_planned", "run_started"]
    assert types[-1] == "run_succeeded"


def test_create_run_validation(client):
    r = client.post("/api/runs", json={"title": "", "input_text": ""})
    assert r.status_code == 422
    r2 = client.post("/api/runs", json={"title": "x" * 65, "input_text": "ok"})
    assert r2.status_code == 422


def test_list_runs_pagination_and_filter(client):
    a = db.create_run("A", "文本A", db.now_iso())
    b = db.create_run("B", "文本B", db.now_iso())
    db.update_run(a, status="succeeded", finished_at=db.now_iso())
    db.update_run(b, status="succeeded", finished_at=db.now_iso())
    body = client.get("/api/runs").json()
    assert body["total"] == 2
    assert [i["title"] for i in body["items"]] == ["B", "A"]
    assert client.get("/api/runs", params={"status": "succeeded"}).json()["total"] == 2
    assert client.get("/api/runs", params={"query": "文本"}).json()["total"] == 2
    assert client.get("/api/runs", params={"query": "不存在"}).json()["total"] == 0
    page = client.get("/api/runs", params={"page": 1, "page_size": 1}).json()
    assert len(page["items"]) == 1 and page["total"] == 2


def test_get_run_detail_with_planned_steps(client):
    run_id = db.create_run("任务", "分析竞争产品", db.now_iso())
    planner.plan_run(run_id)  # A3：规划后仍为 pending，steps 已落库
    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["run"]["id"] == run_id
    assert detail["run"]["status"] == "pending"
    steps = detail["steps"]
    assert len(steps) >= 4
    keys = {s["step_key"] for s in steps}
    for i, s in enumerate(steps, start=1):
        assert s["run_id"] == run_id
        assert s["seq"] == i
        assert s["status"] == "pending"
        assert s["name"] and s["role"] and s["prompt"]
        assert s["kind"] in ("llm", "tool", "approval", "report")
        assert isinstance(s["depends_on"], list)
        assert set(s["depends_on"]) <= keys


def test_get_run_404(client):
    assert client.get("/api/runs/9999").status_code == 404


def test_cancel_run(client):
    # pending 可取消
    rid = db.create_run("手动任务", "手动创建，未触发规划", db.now_iso())
    r = client.post(f"/api/runs/{rid}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    assert r.json()["finished_at"] is not None
    # 终态不可再取消
    assert client.post(f"/api/runs/{rid}/cancel").status_code == 409
    # running 不可取消（A3）
    rid2 = db.create_run("运行中", "执行中", db.now_iso())
    db.update_run(rid2, status="running")
    assert client.post(f"/api/runs/{rid2}/cancel").status_code == 409
    # succeeded 不可取消
    rid3 = db.create_run("已完成", "已完成", db.now_iso())
    db.update_run(rid3, status="succeeded", finished_at=db.now_iso())
    assert client.post(f"/api/runs/{rid3}/cancel").status_code == 409
    # 不存在 → 404
    assert client.post("/api/runs/9999/cancel").status_code == 404


def test_events_after_cancel(client):
    # 未规划任务取消产生 run_cancelled
    rid = db.create_run("手动任务", "手动创建", db.now_iso())
    client.post(f"/api/runs/{rid}/cancel")
    events = client.get(f"/api/runs/{rid}/events").json()
    assert len(events) == 1
    assert events[0]["type"] == "run_cancelled"
    assert events[0]["seq"] == 1
    # 增量协议：after=最后 seq 无新事件
    last_seq = events[-1]["seq"]
    assert client.get(f"/api/runs/{rid}/events", params={"after": last_seq}).json() == []
    # 规划过程产生 run_planning / run_planned
    rid2 = db.create_run("规划任务", "规划", db.now_iso())
    planner.plan_run(rid2)
    events = client.get(f"/api/runs/{rid2}/events").json()
    assert [e["type"] for e in events] == ["run_planning", "run_planned"]
    # 事件 404
    assert client.get("/api/runs/9999/events").status_code == 404


def test_delete_run(client):
    rid = db.create_run("任务", "待删除", db.now_iso())
    r = client.delete(f"/api/runs/{rid}")
    assert r.status_code == 200
    assert client.get(f"/api/runs/{rid}").status_code == 404
    assert client.delete("/api/runs/9999").status_code == 404


def test_approve_step_api(client):
    # 活动策划模板包含 approval 步骤；真实异步流程直达审批挂起
    rid = db.create_run("活动策划", "策划一场产品发布会活动，包含流程与预算。", db.now_iso())
    executor.start_run(rid)
    assert _wait_until(lambda: db.get_run(rid)["status"] == "waiting_approval", 10), "未到达审批挂起"
    approval = next(s for s in db.list_steps(rid) if s["kind"] == "approval")
    assert approval["status"] == "waiting_approval"
    r = client.post(
        f"/api/runs/steps/{approval['id']}/approve",
        json={"action": "approve", "reason": "预算符合要求"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    run = _wait_run(rid)
    assert run["status"] == "succeeded"
    final = {s["step_key"]: s["status"] for s in db.list_steps(rid)}
    assert final["approve"] == "succeeded"
    # 终态步骤不可再审批 → 409
    assert client.post(
        f"/api/runs/steps/{approval['id']}/approve",
        json={"action": "reject", "reason": "x"},
    ).status_code == 409
    # 步骤不存在 → 404
    assert client.post(
        "/api/runs/steps/9999/approve", json={"action": "approve", "reason": "x"}
    ).status_code == 404
