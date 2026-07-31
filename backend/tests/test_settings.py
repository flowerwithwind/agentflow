"""设置 API 测试。"""
from __future__ import annotations


def test_default_settings(client):
    body = client.get("/api/settings").json()
    assert body["model"]["model"] == "deepseek-chat"
    assert body["model"]["api_key"] == ""  # 不回显
    assert body["execution"]["parallel"] == 4
    assert body["capabilities"]["demo_mode"] is True


def test_save_model_settings_keeps_api_key(client):
    r = client.put("/api/settings", json={
        "model": {"model": "gpt-4o-mini", "temperature": 0.5, "api_key": "sk-test-123"},
    })
    assert r.status_code == 200
    body = r.json()
    assert body["model"]["model"] == "gpt-4o-mini"
    assert body["model"]["temperature"] == 0.5
    # 写入后回显掩码
    assert body["model"]["api_key"] == "***"
    assert body["capabilities"]["llm"] is True

    # 再次保存不改 api_key → 保留原值
    r2 = client.put("/api/settings", json={"model": {"model": "qwen-max"}})
    assert r2.json()["model"]["model"] == "qwen-max"
    assert r2.json()["model"]["api_key"] == "***"


def test_save_execution_settings(client):
    r = client.put("/api/settings", json={"execution": {"parallel": 8, "max_attempts": 5}})
    assert r.status_code == 200
    exec_cfg = r.json()["execution"]
    assert exec_cfg["parallel"] == 8
    assert exec_cfg["max_attempts"] == 5
    assert exec_cfg["step_timeout_seconds"] == 120  # 未改动的保持默认


import time

from app.storage import db


def _wait_terminal(run_id, timeout=15.0):
    """等待后台执行线程到达终态，避免清库时线程写事件撞外键。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = db.get_run(run_id)
        if row and row["status"] in ("succeeded", "failed", "cancelled"):
            return row
        time.sleep(0.02)
    raise AssertionError("run 未到达终态")


def test_clear_data_keeps_tools_and_settings(client):
    """数据管理：清库后任务清空，但工具注册表与设置保留。"""
    # 准备一条任务与自定义工具
    r = client.post("/api/runs", json={"title": "测试任务", "input_text": "竞品分析：对比 A 与 B"})
    assert r.status_code == 201
    run_id = r.json()["id"]
    _wait_terminal(run_id)
    client.post("/api/tools", json={"key": "my_tool", "name": "我的工具", "params": {}})
    client.put("/api/settings", json={"model": {"model": "qwen-max"}})

    body = client.post("/api/settings/clear-data").json()
    assert body["cleared"] == "runs"
    assert body["count"] >= 1

    assert client.get(f"/api/runs/{run_id}").status_code == 404
    assert client.get("/api/runs").json()["total"] == 0
    keys = [t["key"] for t in client.get("/api/tools").json()]
    assert "my_tool" in keys and "web_search" in keys  # 自定义与内置工具均保留
    assert client.get("/api/settings").json()["model"]["model"] == "qwen-max"

