"""任务 CRUD 与事件测试（M1：引擎接入前仅记录与状态流转）。"""
from __future__ import annotations


def _payload(title="竞品分析", text="请分析三家竞品的最新动态并给出建议。"):
    return {"title": title, "input_text": text}


def test_create_run(client):
    r = client.post("/api/runs", json=_payload())
    assert r.status_code == 201
    run = r.json()
    assert run["title"] == "竞品分析"
    assert run["status"] == "pending"
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
    assert client.get("/api/runs", params={"status": "pending"}).json()["total"] == 2
    assert client.get("/api/runs", params={"query": "竞品"}).json()["total"] == 2
    assert client.get("/api/runs", params={"query": "不存在"}).json()["total"] == 0
    page = client.get("/api/runs", params={"page": 1, "page_size": 1}).json()
    assert len(page["items"]) == 1 and page["total"] == 2


def test_get_run_detail_with_steps(client):
    run = client.post("/api/runs", json=_payload()).json()
    detail = client.get(f"/api/runs/{run['id']}").json()
    assert detail["run"]["id"] == run["id"]
    assert detail["steps"] == []  # M1 引擎未接入


def test_get_run_404(client):
    assert client.get("/api/runs/9999").status_code == 404


def test_cancel_run(client):
    run = client.post("/api/runs", json=_payload()).json()
    r = client.post(f"/api/runs/{run['id']}/cancel")
    assert r.status_code == 200
    assert r.json()["status"] == "cancelled"
    assert r.json()["finished_at"] is not None
    # 终态不可再取消
    assert client.post(f"/api/runs/{run['id']}/cancel").status_code == 409


def test_events_after_cancel(client):
    run = client.post("/api/runs", json=_payload()).json()
    client.post(f"/api/runs/{run['id']}/cancel")
    events = client.get(f"/api/runs/{run['id']}/events").json()
    assert len(events) == 1
    assert events[0]["type"] == "run_cancelled"
    assert events[0]["seq"] == 1
    # 增量协议：after=1 无新事件
    assert client.get(f"/api/runs/{run['id']}/events", params={"after": 1}).json() == []
    # 事件 404
    assert client.get("/api/runs/9999/events").status_code == 404


def test_delete_run(client):
    run = client.post("/api/runs", json=_payload()).json()
    r = client.delete(f"/api/runs/{run['id']}")
    assert r.status_code == 200
    assert client.get(f"/api/runs/{run['id']}").status_code == 404
    assert client.delete("/api/runs/9999").status_code == 404
