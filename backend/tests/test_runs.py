"""任务 CRUD 与事件测试（A2：创建即规划，状态 pending → planning → succeeded/failed）。"""
from __future__ import annotations

from app.storage import db


def _payload(title="竞品分析", text="请分析三家竞品的最新动态并给出建议。"):
    return {"title": title, "input_text": text}


def test_create_run(client):
    r = client.post("/api/runs", json=_payload())
    assert r.status_code == 201
    run = r.json()
    assert run["title"] == "竞品分析"
    # A2：POST 创建后立即规划（无 Key 走规则规划器），规划完成进入 succeeded
    assert run["status"] == "succeeded"
    assert run["total_tokens"] == 0
    assert run["id"] > 0


def test_create_run_validation(client):
    r = client.post("/api/runs", json={"title": "", "input_text": ""})
    assert r.status_code == 422
    r2 = client.post("/api/runs", json={"title": "x" * 65, "input_text": "ok"})
    assert r2.status_code == 422


def test_list_runs_pagination_and_filter(client):
    client.post("/api/runs", json=_payload(title="A"))
    client.post("/api/runs", json=_payload(title="B"))
    body = client.get("/api/runs").json()
    assert body["total"] == 2
    assert [i["title"] for i in body["items"]] == ["B", "A"]
    assert client.get("/api/runs", params={"status": "succeeded"}).json()["total"] == 2
    assert client.get("/api/runs", params={"query": "竞品"}).json()["total"] == 2
    assert client.get("/api/runs", params={"query": "不存在"}).json()["total"] == 0
    page = client.get("/api/runs", params={"page": 1, "page_size": 1}).json()
    assert len(page["items"]) == 1 and page["total"] == 2


def test_get_run_detail_with_planned_steps(client):
    run = client.post("/api/runs", json=_payload()).json()
    detail = client.get(f"/api/runs/{run['id']}").json()
    assert detail["run"]["id"] == run["id"]
    steps = detail["steps"]
    assert len(steps) >= 4  # A2：创建即规划，步骤已落库
    keys = {s["step_key"] for s in steps}
    for i, s in enumerate(steps, start=1):
        assert s["run_id"] == run["id"]
        assert s["seq"] == i
        assert s["status"] == "pending"
        assert s["name"] and s["role"]
        assert s["kind"] in ("llm", "tool", "approval", "report")
        assert isinstance(s["depends_on"], list)
        assert set(s["depends_on"]) <= keys


def test_get_run_404(client):
    assert client.get("/api/runs/9999").status_code == 404


def test_cancel_run(client):
    # A2：POST 创建即完成规划（终态 succeeded），不可取消
    run = client.post("/api/runs", json=_payload()).json()
    assert run["status"] == "succeeded"
    assert client.post(f"/api/runs/{run['id']}/cancel").status_code == 409
    # 未触发规划的 pending 任务可取消
    rid = db.create_run("手动任务", "手动创建，未触发规划", db.now_iso())
    r = client.post(f"/api/runs/{rid}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    assert r.json()["finished_at"] is not None
    # 终态不可再取消
    assert client.post(f"/api/runs/{rid}/cancel").status_code == 409


def test_events_after_cancel(client):
    run = client.post("/api/runs", json=_payload()).json()
    # A2：规划过程产生 run_planning / run_planned 事件
    events = client.get(f"/api/runs/{run['id']}/events").json()
    assert [e["type"] for e in events] == ["run_planning", "run_planned"]
    # 增量协议：after=最后 seq 无新事件
    last_seq = events[-1]["seq"]
    assert client.get(f"/api/runs/{run['id']}/events", params={"after": last_seq}).json() == []
    # 未规划任务取消产生 run_cancelled
    rid = db.create_run("手动任务", "手动创建", db.now_iso())
    client.post(f"/api/runs/{rid}/cancel")
    events = client.get(f"/api/runs/{rid}/events").json()
    assert len(events) == 1
    assert events[0]["type"] == "run_cancelled"
    assert events[0]["seq"] == 1
    # 事件 404
    assert client.get("/api/runs/9999/events").status_code == 404


def test_delete_run(client):
    run = client.post("/api/runs", json=_payload()).json()
    r = client.delete(f"/api/runs/{run['id']}")
    assert r.status_code == 200
    assert client.get(f"/api/runs/{run['id']}").status_code == 404
    assert client.delete("/api/runs/9999").status_code == 404